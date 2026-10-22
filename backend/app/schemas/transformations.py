from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, Field, model_validator


class TransformationPayload(BaseModel):
    format: str = Field(default="JSON")
    payload: Any

    @model_validator(mode='after')
    def detect_text_format(self):
        if isinstance(self.payload, str):
            text = self.payload.lstrip()
            if text.startswith('<'):
                self.format = 'XML'
            elif text.startswith(('{', '[')) and self.format.upper() != 'ISO':
                self.format = 'JSON'
            elif text and all('=' in line for line in text.splitlines() if line.strip()):
                self.format = 'ISO'
        return self


class RequestContext(BaseModel):
    direction: Literal['REQUEST', 'RESPONSE'] = 'RESPONSE'
    additionalProperties: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='before')
    @classmethod
    def request_envelope(cls, values):
        if not isinstance(values,dict):return values
        from app.transformations.input_envelope import unpack
        data=dict(values)
        direction=data.get('direction','RESPONSE')
        if direction!='REQUEST':return data
        source=data.get('source')
        payload=source.get('payload') if isinstance(source,dict) else data.get('input_payload')
        if payload is None:return data
        inner,props,headers=unpack(payload,direction,data.get('additionalProperties'),data.get('headers'))
        data.update(additionalProperties=props,headers=headers)
        if isinstance(source,dict):data['source']={**source,'payload':inner}
        else:
            data['input_payload']=inner
            if isinstance(inner,str) and inner.lstrip().startswith('<'):data['source_format']='XML'
        return data

    @model_validator(mode='after')
    def request_only(self):
        if 'direction' not in self.model_fields_set and '<#-- control-room request context -->' in getattr(self,'template',''):
            self.direction = 'REQUEST'
        if self.direction != 'REQUEST' and (self.additionalProperties or self.headers):
            raise ValueError('additionalProperties and headers are available only for REQUEST transformations.')
        return self


class TransformationChatRequest(RequestContext):
    message: str = ""
    direction: Literal['REQUEST', 'RESPONSE'] = Field(
        description="REQUEST or RESPONSE"
    )
    source: TransformationPayload
    target: TransformationPayload
    validations: list[Dict[str, Any]] = Field(default_factory=list)
    mappings: Dict[str, str] = Field(default_factory=dict)
    use_learned: bool = False
    filters: list[Dict[str, Any]] = Field(default_factory=list, max_length=20)


class TransformationChatResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    next_action: Optional[str] = None


class TransformationExecuteRequest(RequestContext):
    template: str
    input_payload: Any
    approved: bool = False
    source_format: str = "JSON"
    target_format: str = "JSON"
    learning_id: Optional[int] = None


class TransformationFeedbackRequest(BaseModel):
    approved: bool
    comment: str = Field(default='', max_length=2000)


class TransformationTestRequest(RequestContext):
    template: str = Field(min_length=1, max_length=50000)
    input_payload: Any
    source_format: Literal['JSON', 'XML', 'ISO'] = 'JSON'
    target_format: Literal['JSON', 'XML', 'ISO'] = 'JSON'


class TemplateToolsRequest(BaseModel):
    action: Literal['inspect','compare','revise','generate_payload']
    source_format: Literal['JSON','XML','ISO'] = 'JSON'
    direction: Literal['REQUEST','RESPONSE'] = 'REQUEST'
    xml_root: str = Field(default='root',min_length=1,max_length=100)
    template: str = Field(min_length=1, max_length=50000)
    other_template: str = Field(default='', max_length=50000)
    instructions: str = Field(default='', max_length=4000)
    replacements: list[Dict[str, str]] = Field(default_factory=list, max_length=30)
