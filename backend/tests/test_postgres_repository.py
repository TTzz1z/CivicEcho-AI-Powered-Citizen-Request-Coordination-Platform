"""Run inside the backend Compose container against the migrated PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.database import SessionLocal
from app.repositories.postgres import PostgreSQLTicketRepository
from app.schemas import TicketCreate
from app.services.ticket_service import TicketService
from app.authorization import Principal


def make_payload(key=None):
    return TicketCreate(
        idempotency_key=key or str(uuid4()), request_type="求助",
        description="老人需要协助办理业务", location="社区服务中心", source="pytest",
    )


def create_once(data):
    with SessionLocal() as session:
        return TicketService(PostgreSQLTicketRepository(session)).create(data)


def test_postgres_create_query_status_and_history():
    result = create_once(make_payload())
    with SessionLocal() as session:
        service = TicketService(PostgreSQLTicketRepository(session))
        admin = Principal("user", None, "test-admin", "admin", None)
        service.update_status(result.ticket.ticket_id, "accepted", "测试受理", 1, admin)
        detail = service.detail(result.ticket.ticket_id, admin)
        assert detail.status == "accepted"
        assert len(detail.history) == 2


def test_postgres_idempotency_and_concurrent_unique_ids():
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=10) as pool:
        duplicate_results = list(pool.map(lambda _: create_once(make_payload(key)), range(10)))
    assert len({result.ticket.ticket_id for result in duplicate_results}) == 1

    with ThreadPoolExecutor(max_workers=12) as pool:
        unique_results = list(pool.map(lambda _: create_once(make_payload()), range(40)))
    ids = [result.ticket.ticket_id for result in unique_results]
    assert len(ids) == len(set(ids)) == 40
