from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .models import ActivityEvent, Conversation
from .repository import ControlRoomRepository


class ControlRoomService:
    def __init__(self, repository: ControlRoomRepository):
        self.repository = repository

    def record_turn(
        self,
        *,
        user_id: int,
        message: str,
        agent_name: str,
        result_message: str,
        task_type: str,
        success: bool,
        confidence: Optional[float],
        conversation_id: Optional[int] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> Conversation:
        conversation = (
            self.repository.find_conversation(conversation_id, user_id)
            if conversation_id
            else None
        )
        if conversation is None:
            conversation = Conversation(
                user_id=user_id,
                title=message[:120] or "Control Room conversation",
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        conversation.messages.extend([
            {"role": "user", "content": message, "at": timestamp},
            {
                "role": "agent",
                "agent": agent_name,
                "content": result_message,
                "at": timestamp,
            },
        ])
        conversation = self.repository.save_conversation(conversation)

        self.repository.save_activity(ActivityEvent(
            user_id=user_id,
            conversation_id=conversation.id,
            agent_name=agent_name,
            event_type=task_type,
            summary=result_message,
            confidence=confidence,
            status="COMPLETED" if success else "NEEDS_ATTENTION",
            details=result_data or {},
        ))
        return conversation
