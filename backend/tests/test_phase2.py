from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.authorization import Principal
from app.models import CategoryModel
from app.repositories.memory import InMemoryTicketRepository
from app.schemas import TicketCreate
from app.services.ticket_service import TicketService


class Categories:
    def __init__(self):
        self.item = CategoryModel(
            id=3, code="CSGL-GGSS-LD", name="路灯故障", parent_id=2, level=3,
            default_department_id=8, accept_sla_minutes=60, resolve_sla_minutes=1440,
            is_active=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )

    def get(self, category_id):
        return self.item if category_id == self.item.id else None

    def has_active_children(self, _category_id):
        return False


class Departments:
    def get(self, department_id):
        return SimpleNamespace(id=department_id, name="城市管理", is_active=True)


class Audit:
    def __init__(self):
        self.actions = []

    def log(self, _principal, action, _outcome="success", *args, **kwargs):
        self.actions.append((action, kwargs))


def make_ticket(service, principal):
    return service.create(TicketCreate(
        idempotency_key=str(uuid4()), request_type="投诉", description="路灯连续三晚不亮",
        location="幸福路", requested_priority="major", source="pytest",
    ), principal).ticket


def test_requester_priority_is_only_a_hint_and_agent_confirms_sla():
    repository = InMemoryTicketRepository()
    audit = Audit()
    service = TicketService(repository, Departments(), audit, categories=Categories())
    citizen = Principal("user", 1, "citizen", "citizen")
    agent = Principal("user", 2, "agent", "agent")
    ticket = make_ticket(service, citizen)
    assert ticket.requested_priority == "major"
    assert ticket.priority == "normal"
    accepted = service.accept(ticket.ticket_id, 1, "坐席核实分类及紧急程度", agent, 3, "urgent")
    assert accepted.priority == "urgent"
    assert accepted.category_id == 3
    assert accepted.priority_confirmed_at is not None
    # 紧急按分类默认时限的 50% 计算。
    assert timedelta(minutes=29) <= accepted.accept_due_at - accepted.created_at <= timedelta(minutes=31)
    assert timedelta(hours=11, minutes=59) <= accepted.resolve_due_at - accepted.accepted_at <= timedelta(hours=12, minutes=1)
    assert {item[0] for item in audit.actions} >= {"accept_ticket", "confirm_ticket_triage"}


def test_pause_resume_and_reminder_are_versioned_and_audited():
    repository = InMemoryTicketRepository()
    audit = Audit()
    service = TicketService(repository, Departments(), audit, categories=Categories())
    citizen = Principal("user", 11, "citizen", "citizen")
    agent = Principal("user", 12, "agent", "agent")
    staff = Principal("user", 13, "staff", "department_staff", 8)
    ticket = make_ticket(service, citizen)
    service.accept(ticket.ticket_id, 1, "受理", agent, 3, "normal")
    service.assign(ticket.ticket_id, 2, "派发", 8, None, agent)
    service.process(ticket.ticket_id, 3, "开始处理", staff)
    paused = service.pause_sla(ticket.ticket_id, 4, "等待市民补充现场照片", "等待补充材料", staff)
    assert paused.sla_paused_at and paused.sla_pause_reason == "等待补充材料"
    resumed = service.resume_sla(ticket.ticket_id, 5, "材料已补齐", staff)
    assert resumed.sla_paused_at is None and resumed.total_paused_seconds >= 0
    reminded = service.remind(ticket.ticket_id, 6, "请尽快处理", citizen)
    assert reminded.reminder_count == 1 and reminded.version == 7
    assert {item[0] for item in audit.actions} >= {"pause_ticket_sla", "resume_ticket_sla", "remind_ticket"}
