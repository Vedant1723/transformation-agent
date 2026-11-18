from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, Field, model_validator

TransformationType = Literal['JSONTOJSON','JSONTOXML','JSONTOISO','XMLTOJSON','XMLTOXML','XMLTOISO','ISOTOJSON','ISOTOXML','ISOTOISO']


class TransformationPayload(BaseModel):
    format: str = Field(default="JSON")
    payload: Any

    @model_validator(mode='after')
    def detect_text_format(self):
        from app.transformations.json_validation import strict_json
        explicit = 'format' in self.model_fields_set
        self.format = self.format.upper()
        if self.format not in ('JSON', 'XML', 'ISO'):
            raise ValueError('Supported formats: JSON, XML, ISO.')
        if isinstance(self.payload, str):
            text = self.payload.lstrip()
            detected = None
            if text.startswith('<'):
                detected = 'XML'
            elif text.startswith(('{', '[')) and self.format.upper() != 'ISO':
                detected = 'JSON'
            elif text and all('=' in line for line in text.splitlines() if line.strip()):
                detected = 'ISO'
            if detected and explicit and detected != self.format:
                raise ValueError('Payload content conflicts with the declared format.')
            if detected and not explicit:self.format = detected
            if self.format == 'JSON':self.payload = strict_json(self.payload)
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


class MappingDiscoveryRequest(RequestContext):
    type: Optional[TransformationType] = None
    direction: Literal['REQUEST', 'RESPONSE'] = Field(
        description="REQUEST or RESPONSE"
    )
    source: TransformationPayload
    target: TransformationPayload

    @model_validator(mode='before')
    @classmethod
    def normalize_contract(cls, values):
        if not isinstance(values, dict):return values
        data = dict(values)
        formats = None
        if data.get('type') is not None:
            kind = data['type']
            allowed = {s+'TO'+t for s in ('JSON','XML','ISO') for t in ('JSON','XML','ISO')}
            if not isinstance(kind,str) or kind not in allowed:
                raise ValueError('Use a supported type such as JSONTOXML or XMLTOJSON.')
            formats = kind.split('TO',1)
        for index, name in enumerate(('source','target')):
            # Flat payload names are unambiguous even when a business object
            # itself contains fields named payload or format.
            flat = name + '_payload'
            if flat in data:
                if name in data:raise ValueError(f'Send either {flat} or {name}, not both.')
                value = {'payload':data.pop(flat)}
            elif name in data:
                value = data[name]
                value = dict(value) if isinstance(value,dict) and 'payload' in value and set(value) <= {'payload','format'} else {'payload':value}
            else:continue
            if formats:
                if 'format' in value and value['format'] != formats[index]:
                    raise ValueError(f'{name}.format conflicts with type.')
                value['format'] = formats[index]
            data[name] = value
        return data


class TransformationChatRequest(MappingDiscoveryRequest):
    message: str = ""
    validations: list[Dict[str, Any]] = Field(default_factory=list)
    mappings: Dict[str, str] = Field(default_factory=dict,
        description='Optional target-to-source overrides. Omit or send an empty value for automatic mapping.')
    use_learned: bool = False
    filters: list[Dict[str, Any]] = Field(default_factory=list, max_length=20)

    @model_validator(mode='before')
    @classmethod
    def optional_mappings(cls, values):
        if not isinstance(values,dict):return values
        data=dict(values)
        if data.get('mappings') is None or data.get('mappings') == '' or data.get('mappings') == []:
            data['mappings']={}
        return data


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
    type: Optional[Literal['JSONTOJSON','JSONTOXML','JSONTOISO','XMLTOJSON','XMLTOXML','XMLTOISO','ISOTOJSON','ISOTOXML','ISOTOISO']] = Field(
        default=None, description='Transformation type. Payload generation uses the source format before TO.')
    source_format: Literal['JSON','XML','ISO'] = 'JSON'
    direction: Literal['REQUEST','RESPONSE'] = 'REQUEST'
    xml_root: str = Field(default='root',min_length=1,max_length=100)
    template: str = Field(min_length=1, max_length=50000)
    other_template: str = Field(default='', max_length=50000)
    instructions: str = Field(default='', max_length=4000)
    replacements: list[Dict[str, str]] = Field(default_factory=list, max_length=30)

    @model_validator(mode='before')
    @classmethod
    def derive_source_format(cls, values):
        if not isinstance(values, dict) or values.get('type') is None:
            return values
        data = dict(values)
        kind = data['type']
        allowed = {source+'TO'+target for source in ('JSON','XML','ISO') for target in ('JSON','XML','ISO')}
        if not isinstance(kind, str) or kind not in allowed:
            raise ValueError('type must be a supported transformation type, for example JSONTOXML or XMLTOJSON.')
        source = kind.split('TO', 1)[0]
        if 'source_format' in data and data['source_format'] != source:
            raise ValueError('source_format conflicts with type; omit source_format when sending type.')
        data['source_format'] = source
        return data
