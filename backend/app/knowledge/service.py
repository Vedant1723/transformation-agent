from typing import Any, Dict, List, Optional

from .models import KnowledgeItem, KnowledgeScope, KnowledgeType
from .repository import KnowledgeRepository


class KnowledgeService:

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    def learn(
        self,
        knowledge_type: KnowledgeType,
        key: str,
        value: Dict[str, Any],
        confidence: float,
        scope: KnowledgeScope = KnowledgeScope.GLOBAL,
        user_id: Optional[int] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeItem:

        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0 and 1.")

        if scope == KnowledgeScope.USER and user_id is None:
            raise ValueError("user_id is required for USER scoped knowledge.")

        item = KnowledgeItem(
            knowledge_type=knowledge_type,
            key=key,
            value=value,
            confidence=confidence,
            scope=scope,
            user_id=user_id,
            source=source,
            metadata=metadata or {},
        )

        return self.repository.save(item)

    def learn_from_feedback(
        self,
        knowledge_type: KnowledgeType,
        key: str,
        corrected_value: Dict[str, Any],
        user_id: int,
        confidence: float = 0.99,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeItem:

        if user_id is None:
            raise ValueError("user_id is required for feedback.")

        return self.learn(
            knowledge_type=knowledge_type,
            key=key,
            value=corrected_value,
            confidence=confidence,
            scope=KnowledgeScope.USER,
            user_id=user_id,
            source="user-feedback",
            metadata=metadata,
        )
        
    def find(
        self,
        key: str,
        user_id: Optional[int] = None,
    ) -> List[KnowledgeItem]:
        return self.repository.find(key, user_id)

    def find_by_type(
        self,
        knowledge_type: KnowledgeType,
        user_id: Optional[int] = None,
    ) -> List[KnowledgeItem]:
        return self.repository.find_by_type(
            knowledge_type.value,
            user_id,
        )