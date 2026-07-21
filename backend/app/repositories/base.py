from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from ..authorization import Principal
from ..models import TicketFeedbackModel, TicketModel, TicketStatusHistoryModel
from ..schemas import TicketCreate, TicketQuery


@dataclass
class CreateResult:
    ticket: TicketModel
    replayed: bool


@dataclass
class PageResult:
    items: list[TicketModel]
    total: int


class TicketRepository(ABC):
    @abstractmethod
    def create(self, ticket_id: str, data: TicketCreate, creator_user_id: int | None, anonymous_key: str | None) -> CreateResult: ...

    @abstractmethod
    def next_sequence(self) -> int: ...

    @abstractmethod
    def get(self, ticket_id: str) -> Optional[TicketModel]: ...

    @abstractmethod
    def list(self, query: TicketQuery, principal: Principal) -> PageResult: ...

    @abstractmethod
    def transition(
        self, ticket_id: str, expected_version: int, status: str,
        operation_type: str, content: str, operator_user_id: int | None,
        updates: dict, visibility: str = "internal",
    ) -> Optional[TicketModel]: ...

    @abstractmethod
    def feedback_transition(
        self, ticket_id: str, expected_version: int, status: str, content: str,
        operator_user_id: int, updates: dict, rating: str, comment: str | None,
        result: str,
    ) -> Optional[TicketModel]: ...

    @abstractmethod
    def history(self, ticket_id: str) -> List[TicketStatusHistoryModel]: ...

    @abstractmethod
    def feedbacks(self, ticket_id: str) -> List[TicketFeedbackModel]: ...
