"""OpenTelemetry spans and bounded per-process stage latency samples."""
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from functools import wraps
from threading import Lock

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult


class LogSpanExporter(SpanExporter):
    def export(self, spans):
        for span in spans:
            logging.getLogger("trace").info(
                "trace_id=%032x span_id=%016x parent_id=%s stage=%s instrumentation_version=%s model=%s prompt=%s schema=%s embedding=%s retrieval=%s duration_ms=%.3f status=%s",
                span.context.trace_id, span.context.span_id,
                format(span.parent.span_id, "016x") if span.parent else "",
                span.name, span.instrumentation_scope.version or "", span.attributes.get("model.name", ""),
                span.attributes.get("prompt.version", ""), span.attributes.get("response.schema.version", ""),
                span.attributes.get("embedding.version", ""), span.attributes.get("retrieval.version", ""),
                (span.end_time - span.start_time) / 1_000_000, span.status.status_code.name,
            )
        return SpanExportResult.SUCCESS


provider = TracerProvider(resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "civicecho-backend")}))
if os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    exporter = OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
else:
    exporter = LogSpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
tracer = provider.get_tracer("civicecho", "2026-11")
_lock = Lock()
_latencies = defaultdict(lambda: deque(maxlen=2048))


@contextmanager
def stage(name):
    started = time.perf_counter()
    with tracer.start_as_current_span(name, record_exception=False):
        try:
            yield
        except Exception:
            trace.get_current_span().set_status(trace.Status(trace.StatusCode.ERROR))
            raise
        finally:
            with _lock:
                _latencies[name].append((time.perf_counter() - started) * 1000)


@contextmanager
def stream_stage(name):
    """Record a span and latency for a generator without attaching OTel context across yields."""
    started = time.perf_counter()
    span = tracer.start_span(name, record_exception=False)
    try:
        yield span
    except Exception:
        span.set_status(trace.Status(trace.StatusCode.ERROR))
        raise
    finally:
        span.end()
        with _lock:
            _latencies[name].append((time.perf_counter() - started) * 1000)


def observed(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def latency_metrics():
    with _lock:
        snapshots = {name: sorted(values) for name, values in _latencies.items()}
    return {
        name: {
            "sample_count": len(values),
            "p50_ms": round(values[int((len(values) - 1) * 0.50)], 3),
            "p95_ms": round(values[int((len(values) - 1) * 0.95)], 3),
        }
        for name, values in snapshots.items() if values
    }
