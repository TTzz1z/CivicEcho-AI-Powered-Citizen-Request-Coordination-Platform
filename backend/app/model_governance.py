"""Admission and resilience shared by remote generation and embedding."""
import hashlib
import time
import urllib.error
import urllib.request
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from threading import Lock

from sqlalchemy import func, select, text

from .database import SessionLocal
from .models import AiUsageBudgetModel, ModelCallModel, UserModel
from .telemetry import observed
from opentelemetry import trace
import json


model_caller: ContextVar[str] = ContextVar("model_caller", default="system")
CALLS_PER_MINUTE = 12
CALLS_PER_DAY = 100
PLATFORM_CALLS_PER_DAY = 5000
TOKENS_PER_DAY = 200_000
PLATFORM_TOKENS_PER_DAY = 5_000_000
_transient_statuses = {429, 502, 503, 504}
_circuit_lock = Lock()
_circuits: dict[str, tuple[int, float]] = {}


class ModelCallDenied(Exception):
    pass


def reserve_model_call(tokens: int) -> None:
    caller = model_caller.get()
    actor = hashlib.sha256(caller.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with SessionLocal.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(724616021)"))
            call_limit, token_limit = CALLS_PER_DAY, TOKENS_PER_DAY
            if caller.startswith("user:") and caller[5:].isdigit():
                user_id = int(caller[5:])
                role = db.scalar(select(UserModel.role).where(UserModel.id == user_id))
                override = db.scalar(select(AiUsageBudgetModel).where(
                    AiUsageBudgetModel.user_id == user_id
                ))
                if override is None and role:
                    override = db.scalar(select(AiUsageBudgetModel).where(
                        AiUsageBudgetModel.user_id.is_(None), AiUsageBudgetModel.role == role
                    ).order_by(AiUsageBudgetModel.id.desc()).limit(1))
                if override is not None:
                    call_limit = override.daily_llm_call_limit
                    if override.daily_token_limit is not None:
                        token_limit = override.daily_token_limit
            calls, actor_calls, recent, total_tokens, actor_tokens = db.execute(
                select(
                    func.count().filter(ModelCallModel.created_at >= day),
                    func.count().filter(ModelCallModel.actor == actor, ModelCallModel.created_at >= day),
                    func.count().filter(
                        ModelCallModel.actor == actor,
                        ModelCallModel.created_at >= now - timedelta(minutes=1),
                    ),
                    func.coalesce(func.sum(ModelCallModel.tokens).filter(ModelCallModel.created_at >= day), 0),
                    func.coalesce(func.sum(ModelCallModel.tokens).filter(
                        ModelCallModel.actor == actor, ModelCallModel.created_at >= day,
                    ), 0),
                ).where(ModelCallModel.created_at >= min(day, now - timedelta(minutes=1)))
            ).one()
            if recent >= CALLS_PER_MINUTE:
                raise ModelCallDenied("rate_limited")
            if actor_calls >= call_limit or actor_tokens + tokens > token_limit:
                raise ModelCallDenied("budget_exceeded")
            if calls >= PLATFORM_CALLS_PER_DAY or total_tokens + tokens > PLATFORM_TOKENS_PER_DAY:
                raise ModelCallDenied("platform_budget_exceeded")
            db.add(ModelCallModel(actor=actor, created_at=now, tokens=tokens))
    except ModelCallDenied:
        raise
    except Exception as exc:
        raise ModelCallDenied("budget_unavailable") from exc


@observed("model.http")
def read_model_response(request: urllib.request.Request, timeout: float, tokens: int) -> bytes:
    endpoint = request.full_url
    try:
        model = json.loads(request.data or b"{}").get("model")
        if isinstance(model, str):
            trace.get_current_span().set_attribute("model.name", model)
    except (ValueError, AttributeError):
        pass
    if timeout <= 0:
        raise TimeoutError("model deadline exceeded")
    with _circuit_lock:
        if _circuits.get(endpoint, (0, 0.0))[1] > time.monotonic():
            raise ModelCallDenied("circuit_open")
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        if time.monotonic() >= deadline:
            raise TimeoutError("model deadline exceeded")
        reserve_model_call(tokens)
        try:
            with urllib.request.urlopen(request, timeout=max(0.1, deadline - time.monotonic())) as response:
                result = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in _transient_statuses:
                raise
            with _circuit_lock:
                previous_failures, open_until = _circuits.get(endpoint, (0, 0.0))
                failures = previous_failures + 1
                if open_until > time.monotonic():
                    failures = max(failures, 3)
                else:
                    _circuits[endpoint] = (0, time.monotonic() + 30) if failures >= 3 else (failures, 0.0)
            if failures >= 3 or attempt or time.monotonic() + 0.25 >= deadline:
                raise
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            time.sleep(0.2)
        else:
            with _circuit_lock:
                _circuits.pop(endpoint, None)
            return result
    raise AssertionError("model retry loop exhausted")


def record_model_stream_success(endpoint: str) -> None:
    """Clear circuit breaker failure count after a successful model stream."""
    with _circuit_lock:
        _circuits.pop(endpoint, None)


def record_model_stream_failure(endpoint: str) -> None:
    """Increment failure count and open circuit for 30s after 3 consecutive stream failures."""
    with _circuit_lock:
        previous_failures, open_until = _circuits.get(endpoint, (0, 0.0))
        failures = previous_failures + 1
        if open_until > time.monotonic():
            failures = max(failures, 3)
        else:
            _circuits[endpoint] = (0, time.monotonic() + 30) if failures >= 3 else (failures, 0.0)


@observed("model.http.stream")
def open_model_stream(request: urllib.request.Request, timeout: float, tokens: int) -> tuple[object, float]:
    """Open an upstream SSE HTTP stream with shared quota reservation, retry, and circuit breaker."""
    endpoint = request.full_url
    try:
        model = json.loads(request.data or b"{}").get("model")
        if isinstance(model, str):
            trace.get_current_span().set_attribute("model.name", model)
    except (ValueError, AttributeError):
        pass
    if timeout <= 0:
        raise TimeoutError("model deadline exceeded")
    with _circuit_lock:
        if _circuits.get(endpoint, (0, 0.0))[1] > time.monotonic():
            raise ModelCallDenied("circuit_open")
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        if time.monotonic() >= deadline:
            raise TimeoutError("model deadline exceeded")
        reserve_model_call(tokens)
        try:
            response = urllib.request.urlopen(request, timeout=max(0.1, deadline - time.monotonic()))
            return response, deadline
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in _transient_statuses:
                raise
            with _circuit_lock:
                previous_failures, open_until = _circuits.get(endpoint, (0, 0.0))
                failures = previous_failures + 1
                if open_until > time.monotonic():
                    failures = max(failures, 3)
                else:
                    _circuits[endpoint] = (0, time.monotonic() + 30) if failures >= 3 else (failures, 0.0)
            if failures >= 3 or attempt or time.monotonic() + 0.25 >= deadline:
                raise
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            time.sleep(0.2)
    raise AssertionError("model stream retry loop exhausted")
