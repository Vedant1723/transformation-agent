from app.core.observability import traced as _log_traced, exception_event as _log_exception
from abc import ABC, abstractmethod
from typing import List, Optional

from .models import KnowledgeItem


class KnowledgeRepository(ABC):

    @abstractmethod
    @_log_traced('app.knowledge.repository.KnowledgeRepository.save', level=10)
    def save(
        self,
        item: KnowledgeItem
    ) -> KnowledgeItem:
        pass

    @abstractmethod
    @_log_traced('app.knowledge.repository.KnowledgeRepository.find', level=10)
    def find(
        self,
        key: str,
        user_id: Optional[int] = None
    ) -> List[KnowledgeItem]:
        pass

    @abstractmethod
    @_log_traced('app.knowledge.repository.KnowledgeRepository.find_by_type', level=10)
    def find_by_type(
        self,
        knowledge_type: str,
        user_id: Optional[int] = None
    ) -> List[KnowledgeItem]:
        pass