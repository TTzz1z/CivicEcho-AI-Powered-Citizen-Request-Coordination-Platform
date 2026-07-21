"""Deterministic in-memory ticket storage for the public-request MVP."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    request_type: str
    description: str
    location: str
    event: Optional[str]
    time: Optional[str]
    target: Optional[str]
    contact: Optional[str]
    created_at: str
    status: str = "待受理"


def china_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


class InMemoryTicketStore:
    """Process-local repository; data intentionally disappears on restart."""

    def __init__(self, clock: Callable[[], datetime] = china_now) -> None:
        self._clock = clock
        self._tickets: Dict[str, Ticket] = {}
        self._daily_sequences: Dict[str, int] = {}
        self._lock = Lock()

    def _next_ticket_id(self, now: datetime) -> str:
        date_part = now.strftime("%Y%m%d")
        sequence = self._daily_sequences.get(date_part, 0) + 1
        self._daily_sequences[date_part] = sequence
        return f"QT{date_part}{sequence:04d}"

    def create_ticket(
        self,
        request_type: str,
        description: str,
        location: str,
        event: Optional[str] = None,
        time: Optional[str] = None,
        target: Optional[str] = None,
        contact: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        with self._lock:
            now = self._clock()
            ticket = Ticket(
                ticket_id=self._next_ticket_id(now),
                request_type=request_type,
                description=description,
                location=location,
                event=event,
                time=time,
                target=target,
                contact=contact,
                created_at=now.isoformat(timespec="seconds"),
            )
            self._tickets[ticket.ticket_id] = ticket
            return asdict(ticket)

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Optional[str]]]:
        ticket = self._tickets.get(ticket_id.upper())
        return asdict(ticket) if ticket else None

    def query_tickets(self, **criteria: str) -> List[Dict[str, Optional[str]]]:
        results = []
        for ticket in self._tickets.values():
            data = asdict(ticket)
            if all(data.get(key) == value for key, value in criteria.items()):
                results.append(data)
        return results

    def update_ticket_status(
        self, ticket_id: str, status: str
    ) -> Optional[Dict[str, Optional[str]]]:
        with self._lock:
            current = self._tickets.get(ticket_id.upper())
            if not current:
                return None
            updated = Ticket(**{**asdict(current), "status": status})
            self._tickets[updated.ticket_id] = updated
            return asdict(updated)

    def clear(self) -> None:
        with self._lock:
            self._tickets.clear()
            self._daily_sequences.clear()


ticket_store = InMemoryTicketStore()
