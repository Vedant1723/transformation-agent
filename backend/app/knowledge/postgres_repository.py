from app.core.observability import traced as _log_traced, exception_event as _log_exception
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import KnowledgeItemModel
from .models import KnowledgeItem

from .repository import KnowledgeRepository

class PostgresKnowledgeRepository(KnowledgeRepository):

    @_log_traced('app.knowledge.postgres_repository.PostgresKnowledgeRepository.__init__', level=10)
    def __init__(self, db: Session):
        self.db = db

    @_log_traced('app.knowledge.postgres_repository.PostgresKnowledgeRepository.save', level=10)
    def save(
        self,
        item: KnowledgeItem
    ) -> KnowledgeItem:

        model = KnowledgeItemModel(
            knowledge_type=item.knowledge_type.value,
            key=item.key,
            value=item.value,
            confidence=item.confidence,
            scope=item.scope.value,
            user_id=item.user_id,
            source=item.source,
            metadata_json=item.metadata
        )

        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)

        return self._to_domain(model)

    @_log_traced('app.knowledge.postgres_repository.PostgresKnowledgeRepository.find', level=10)
    def find(
        self,
        key: str,
        user_id: Optional[int] = None
    ) -> List[KnowledgeItem]:

        statement = (
            select(KnowledgeItemModel)
            .where(
                KnowledgeItemModel.key == key
            )
            .where(
                (
                    KnowledgeItemModel.scope == "GLOBAL"
                )
                |
                (
                    (KnowledgeItemModel.scope == "USER")
                    &
                    (KnowledgeItemModel.user_id == user_id)
                )
            )
        )

        models = self.db.scalars(statement).all()

        return [
            self._to_domain(model)
            for model in models
        ]

    @_log_traced('app.knowledge.postgres_repository.PostgresKnowledgeRepository.find_by_type', level=10)
    def find_by_type(
        self,
        knowledge_type: str,
        user_id: Optional[int] = None
    ) -> List[KnowledgeItem]:

        statement = (
            select(KnowledgeItemModel)
            .where(
                KnowledgeItemModel.knowledge_type
                == knowledge_type
            )
            .where(
                (
                    KnowledgeItemModel.scope == "GLOBAL"
                )
                |
                (
                    (KnowledgeItemModel.scope == "USER")
                    &
                    (KnowledgeItemModel.user_id == user_id)
                )
            )
        )

        models = self.db.scalars(statement).all()

        return [
            self._to_domain(model)
            for model in models
        ]

    @staticmethod
    @_log_traced('app.knowledge.postgres_repository.PostgresKnowledgeRepository._to_domain', level=10)
    def _to_domain(
        model: KnowledgeItemModel
    ) -> KnowledgeItem:

        from .models import (
            KnowledgeScope,
            KnowledgeType
        )

        return KnowledgeItem(
            knowledge_type=KnowledgeType(
                model.knowledge_type
            ),
            key=model.key,
            value=model.value,
            confidence=model.confidence,
            scope=KnowledgeScope(
                model.scope
            ),
            user_id=model.user_id,
            source=model.source,
            metadata=model.metadata_json
        )