from app.core.observability import traced as _log_traced, exception_event as _log_exception
from abc import ABC, abstractmethod
from typing import List, Optional

from .models import ActivityEvent, Conversation


class ControlRoomRepository(ABC):
    @abstractmethod
    @_log_traced('app.control_room.repository.ControlRoomRepository.save_conversation', level=10)
    def save_conversation(self, conversation: Conversation) -> Conversation:
        pass

    @abstractmethod
    @_log_traced('app.control_room.repository.ControlRoomRepository.find_conversation', level=10)
    def find_conversation(
        self, conversation_id: int, user_id: int
    ) -> Optional[Conversation]:
        pass

    @abstractmethod
    @_log_traced('app.control_room.repository.ControlRoomRepository.save_activity', level=10)
    def save_activity(self, event: ActivityEvent) -> ActivityEvent:
        pass

    @abstractmethod
    @_log_traced('app.control_room.repository.ControlRoomRepository.list_activity', level=10)
    def list_activity(self, user_id: int, limit: int = 50) -> List[ActivityEvent]:
        pass
