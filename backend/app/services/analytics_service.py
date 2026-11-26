from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..authorization import AuthorizationPolicy
from ..models import TicketModel
from ..repositories.analytics import AnalyticsRepository
from ..repositories.identity import AuditRepository
from ..schemas import AuditLogList, DashboardData, DashboardMetric, DashboardSlice, DashboardTrendPoint, DepartmentSlaStat, STATUS_LABELS


class AnalyticsService:
    def __init__(self, analytics: AnalyticsRepository, audit: AuditRepository, tickets):
        self.analytics = analytics
        self.audit = audit
        self.tickets = tickets

    def dashboard(self, principal):
        AuthorizationPolicy.require_roles(principal, "admin")
        status = dict(self.analytics.counts_by(TicketModel.status))
        request_types = self.analytics.counts_by(TicketModel.request_type)
        total = sum(status.values())
        soon, overdue, avg_accept, avg_resolve = self.analytics.sla_summary()
        department_sla = self.analytics.department_sla()
        timezone_name = "Asia/Shanghai"
        today = datetime.now(ZoneInfo(timezone_name)).date()
        first_day = today - timedelta(days=13)
        intake = self.analytics.daily_intake(first_day, today + timedelta(days=1), timezone_name)
        days = [first_day + timedelta(days=offset) for offset in range(14)]
        return DashboardData(
            metrics=[
                DashboardMetric(key="total", label="工单总数", value=total),
                DashboardMetric(key="due_soon", label="即将超时", value=soon),
                DashboardMetric(key="overdue", label="已超时", value=overdue),
                DashboardMetric(key="avg_accept", label="平均受理时长", value=avg_accept or 0, unit="分钟", has_samples=avg_accept is not None),
                DashboardMetric(key="avg_resolve", label="平均办理时长", value=avg_resolve or 0, unit="分钟", has_samples=avg_resolve is not None),
            ],
            status_distribution=[DashboardSlice(name=STATUS_LABELS.get(k, k), value=v) for k, v in status.items()],
            request_type_distribution=[DashboardSlice(name=k, value=v) for k, v in request_types],
            department_distribution=[DashboardSlice(name=k, value=v) for k, v in self.analytics.department_counts()],
            department_sla=[DepartmentSlaStat(
                department_name=name, total=department_total, overdue=department_overdue,
                overdue_rate=round(department_overdue * 100 / department_total, 1) if department_total else 0,
            ) for name, department_total, department_overdue in department_sla],
            recent_tickets=[self.tickets._present(item, principal) for item in self.analytics.recent()],
            intake_trend=[DashboardTrendPoint(day=day, count=intake.get(day, 0)) for day in days],
            trend_timezone=timezone_name,
        )

    def audit_logs(self, principal, page, page_size, action=None):
        AuthorizationPolicy.require_roles(principal, "admin")
        items, total = self.audit.list(page, page_size, action)
        return AuditLogList(items=items, page=page, page_size=page_size, total=total)

    def export_audit_logs(
        self,
        principal,
        *,
        action: str | None = None,
        outcome: str | None = None,
        q: str | None = None,
        limit: int = 5000,
    ):
        AuthorizationPolicy.require_roles(principal, "admin")
        items = self.audit.list_for_export(action=action, outcome=outcome, q=q, limit=limit)
        self.audit.log(
            principal,
            "export_audit_logs",
            details={"count": len(items), "action": action, "outcome": outcome, "q": q},
        )
        return items
