from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Conversation:
    user_id: int
    title: str
    id: Optional[int] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ActivityEvent:
    user_id: int
    agent_name: str
    event_type: str
    summary: str
    confidence: Optional[float] = None
    conversation_id: Optional[int] = None
    status: str = "COMPLETED"
    details: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None
    created_at: Optional[datetime] = None
