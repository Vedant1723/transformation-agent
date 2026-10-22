from app.core.observability import traced as _log_traced, exception_event as _log_exception
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import ActivityEventModel, ConversationModel
from .models import ActivityEvent, Conversation
from .repository import ControlRoomRepository


class PostgresControlRoomRepository(ControlRoomRepository):
    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository.__init__', level=10)
    def __init__(self, db: Session):
        self.db = db

    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository.save_conversation', level=10)
    def save_conversation(self, conversation: Conversation) -> Conversation:
        if conversation.id is None:
            model = ConversationModel(
                user_id=conversation.user_id,
                title=conversation.title,
                messages_json=conversation.messages,
            )
            self.db.add(model)
        else:
            model = self.db.get(ConversationModel, conversation.id)
            if model is None or model.user_id != conversation.user_id:
                raise ValueError("Conversation not found.")
            model.title = conversation.title
            model.messages_json = conversation.messages

        self.db.commit()
        self.db.refresh(model)
        return self._to_conversation(model)

    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository.find_conversation', level=10)
    def find_conversation(
        self, conversation_id: int, user_id: int
    ) -> Optional[Conversation]:
        model = self.db.scalar(
            select(ConversationModel).where(
                ConversationModel.id == conversation_id,
                ConversationModel.user_id == user_id,
            )
        )
        return self._to_conversation(model) if model else None

    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository.save_activity', level=10)
    def save_activity(self, event: ActivityEvent) -> ActivityEvent:
        model = ActivityEventModel(
            user_id=event.user_id,
            conversation_id=event.conversation_id,
            agent_name=event.agent_name,
            event_type=event.event_type,
            summary=event.summary,
            confidence=event.confidence,
            status=event.status,
            details_json=event.details,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_activity(model)

    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository.list_activity', level=10)
    def list_activity(self, user_id: int, limit: int = 50) -> List[ActivityEvent]:
        models = self.db.scalars(
            select(ActivityEventModel)
            .where(ActivityEventModel.user_id == user_id)
            .order_by(ActivityEventModel.created_at.desc())
            .limit(limit)
        ).all()
        return [self._to_activity(model) for model in models]

    @staticmethod
    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository._to_conversation', level=10)
    def _to_conversation(model: ConversationModel) -> Conversation:
        return Conversation(
            id=model.id,
            user_id=model.user_id,
            title=model.title,
            messages=model.messages_json or [],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    @_log_traced('app.control_room.postgres_repository.PostgresControlRoomRepository._to_activity', level=10)
    def _to_activity(model: ActivityEventModel) -> ActivityEvent:
        return ActivityEvent(
            id=model.id,
            user_id=model.user_id,
            conversation_id=model.conversation_id,
            agent_name=model.agent_name,
            event_type=model.event_type,
            summary=model.summary,
            confidence=model.confidence,
            status=model.status,
            details=model.details_json or {},
            created_at=model.created_at,
        )
