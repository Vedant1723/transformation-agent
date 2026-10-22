"""Public feedback contract, independent of HTTP route registration."""
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.transformations import TransformationChatRequest
from app.schemas.correction import CorrectionCase


class Feedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: TransformationChatRequest
    template: str = Field(min_length=1, max_length=50000)
    expected_output: str = Field(min_length=1, max_length=50000)
    comment: str = Field(default='', max_length=2000)
    approved: bool = False
    sanitized: bool = False
    validation_cases: list[CorrectionCase] = Field(default_factory=list, max_length=8)
