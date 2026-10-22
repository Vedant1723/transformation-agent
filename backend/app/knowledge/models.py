from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class KnowledgeScope(str, Enum):
    GLOBAL = "GLOBAL"
    USER = "USER"


class KnowledgeType(str, Enum):
    FIELD_MAPPING = "FIELD_MAPPING"
    TRANSFORMATION_PATTERN = "TRANSFORMATION_PATTERN"
    CONTRACT_PATTERN = "CONTRACT_PATTERN"
    VALIDATION_PATTERN = "VALIDATION_PATTERN"
    INCIDENT_PATTERN = "INCIDENT_PATTERN"


@dataclass
class KnowledgeItem:
    knowledge_type: KnowledgeType
    key: str
    value: Dict[str, Any]
    confidence: float
    scope: KnowledgeScope = KnowledgeScope.GLOBAL
    user_id: Optional[int] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
