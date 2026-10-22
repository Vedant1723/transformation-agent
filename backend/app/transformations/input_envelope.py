"""Organisation request envelope; response payloads are never unwrapped."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
from typing import Any

from app.transformations.json_validation import strict_json

ENVELOPE_FIELDS = frozenset({'inputRequest', 'headers', 'additionalProperties'})


@_log_traced('app.transformations.input_envelope._resolve_metadata', level=10)
def _resolve_metadata(envelope: dict, name: str, separate: dict) -> dict:
    """Reject ambiguous metadata rather than silently selecting one copy."""
    value = envelope.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f'{name} must be an object.')
    if name in envelope and separate and separate != value:
        raise ValueError(f'Conflicting {name} in envelope and separate field.')
    return value if name in envelope else separate


@_log_traced('app.transformations.input_envelope.unpack', level=10)
def unpack(
    payload: Any,
    direction: str,
    properties: dict | None = None,
    headers: dict | None = None,
) -> tuple[Any, dict, dict]:
    """Return basic input, additional properties and headers without mutation."""
    properties = properties or {}
    headers = headers or {}
    if direction != 'REQUEST':
        return payload, properties, headers
    candidate = payload
    if isinstance(candidate, str) and candidate.lstrip().startswith('{'):
        candidate = strict_json(candidate)
    if not isinstance(candidate, dict) or 'inputRequest' not in candidate:
        return payload, properties, headers
    if set(candidate) - ENVELOPE_FIELDS:
        raise ValueError('Request envelope supports only inputRequest, headers and additionalProperties.')
    inner = candidate['inputRequest']
    if not isinstance(inner, (dict, str)):
        raise ValueError('inputRequest must be a JSON object, JSON string or XML string.')
    resolved_properties = _resolve_metadata(candidate, 'additionalProperties', properties)
    resolved_headers = _resolve_metadata(candidate, 'headers', headers)
    if isinstance(inner, str) and inner.lstrip().startswith('{'):
        inner = strict_json(inner)
    return inner, resolved_properties, resolved_headers
