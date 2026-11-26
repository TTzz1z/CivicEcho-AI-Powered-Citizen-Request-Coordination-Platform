"""Run inside the backend Compose container against the migrated PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.authorization import Principal
from app.database import SessionLocal
from app.models import CategoryModel, DepartmentModel, TicketModel, UserModel
from app.repositories.postgres import PostgreSQLTicketRepository
from app.schemas import TicketCreate, TicketQuery
from app.services.ticket_service import TicketService


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


def test_ticket_page_projection_needs_two_queries_for_distinct_associations():
    marker = uuid4().hex[:12]
    with SessionLocal() as setup:
        for index in range(6):
            tag = f"{marker}_{index}"
            owner = UserModel(username=f"owner_{tag}", password_hash="unused", display_name=f"Owner {index}", role="citizen")
            department = DepartmentModel(code=f"DEPT_{tag}", name=f"Dept {tag}")
            area = CategoryModel(code=f"AREA_{tag}", name="Area", level=1)
            subject = CategoryModel(code=f"SUBJ_{tag}", name="Topic", level=2, parent=area)
            leaf = CategoryModel(code=f"LEAF_{tag}", name="Leaf", level=3, parent=subject)
            setup.add(TicketModel(ticket_id=f"QT{tag.upper()}", idempotency_key=f"idem_{tag}", request_type="投诉",
                                  description=marker, location="测试道路", creator=owner, category=leaf, department=department))
        setup.flush()
        with Session(bind=setup.connection()) as db:
            connection = db.connection()
            queries = []

            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                queries.append(statement)

            event.listen(connection, "before_cursor_execute", capture)
            try:
                service = TicketService(PostgreSQLTicketRepository(db))
                page = service.list_tickets(TicketQuery(keyword=marker), Principal("user", role="admin"))
                assert page.total == 6 and len(page.items) == 6
                assert {item.category_path for item in page.items} == {"Area / Topic / Leaf"}
                assert all(item.creator_name and item.department_name for item in page.items)
                assert len(queries) == 2
            finally:
                event.remove(connection, "before_cursor_execute", capture)
