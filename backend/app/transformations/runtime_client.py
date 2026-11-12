from app.core.observability import traced as _log_traced, exception_event as _log_exception
from typing import Any, Dict
import json

import httpx
from dataclasses import replace
from app.core.runtime_settings import RuntimeSettings
from app.transformations.request_context import runtime_template


class FreeMarkerRuntimeClient:

    @_log_traced('app.transformations.runtime_client.FreeMarkerRuntimeClient.__init__', level=10)
    def __init__(self, base_url: str | None = None, *, settings: RuntimeSettings | None = None):
        self.settings = settings or RuntimeSettings.from_environment()
        if base_url is not None:
            self.settings = replace(self.settings, base_url=base_url.rstrip('/'))
        self.base_url = self.settings.base_url

    @_log_traced('app.transformations.runtime_client.FreeMarkerRuntimeClient.health', level=10)
    def health(self, timeout=3.0):
        if self.settings.protocol == 'sculpt':
            return {'status': 'NOT_CHECKED', 'reason': 'Sculpt has no health endpoint.'}
        response = httpx.get(
            self.base_url + self.settings.health_path,
            headers=self.settings.headers(), timeout=min(timeout, self.settings.timeout_seconds),
        )
        response.raise_for_status()
        return response.json()

    @_log_traced('app.transformations.runtime_client.FreeMarkerRuntimeClient.execute', level=10)
    def execute(
        self,
        template: str,
        input_payload: Any,
        direction: str = 'RESPONSE',
        additionalProperties=None,
        headers=None,
        source_format='JSON',
        target_format='JSON',
        ideal_object=None,
    ) -> Dict[str, Any]:

        path = self.settings.transform_path
        body = {
                "template": runtime_template(template, direction),
                "input": input_payload,
                "direction": direction,
                "additionalProperties": additionalProperties or {},
                "headers": headers or {},
            }
        if self.settings.protocol == 'sculpt':
            if direction not in ('REQUEST', 'RESPONSE'):
                raise ValueError('Direction must be REQUEST or RESPONSE.')
            source_format, target_format = source_format.upper(), target_format.upper()
            if source_format not in ('JSON', 'XML', 'ISO') or target_format not in ('JSON', 'XML', 'ISO'):
                raise ValueError('Unsupported transformation format.')
            body = {'type': source_format + 'TO' + target_format,
                    'template': runtime_template(template, direction)}
            if direction == 'REQUEST':
                path = self.settings.request_path
                body['input'] = {'inputRequest': input_payload, 'inputHeaders': headers or {},
                                 'additionalProperties': additionalProperties or {}}
            else:
                path = self.settings.response_path
                body.update(responseObj=input_payload,
                    # Sculpt renders only; expected-output comparison stays local.
                    idealObject='',
                    input={'additionalProperties': additionalProperties or {}})
        response = httpx.post(
            self.base_url + path,
            json=body,
            headers=self.settings.headers(),
            timeout=self.settings.timeout_seconds,
        )

        response.raise_for_status()

        try:
            result = response.json()
            if self.settings.protocol == 'sculpt':
                if not isinstance(result, dict) or type(result.get('st')) is not bool:
                    raise ValueError('Invalid Sculpt response.')
                if result['st']:
                    if not isinstance(result.get('data'), str):
                        raise ValueError('Sculpt output must be text.')
                    result = {'success': True, 'output': result['data']}
                else:
                    detail = result.get('validationError') or result.get('devErrorMessage') or result.get('msg') or 'Sculpt rejected the transformation.'
                    result = {'success': False, 'output': '', 'error': detail if isinstance(detail, str) else json.dumps(detail)}
            if not isinstance(result, dict) or not isinstance(result.get('success'), bool):
                raise ValueError('Invalid execution response.')
            if result['success'] and not isinstance(result.get('output'), str):
                raise ValueError('Execution output must be text.')
        except ValueError:
            # Treat a broken upstream contract as unavailable infrastructure, not a bad template.
            _log_exception('app.transformations.runtime_client:55', handled=True)
            raise httpx.HTTPStatusError(
                'Java execution service returned an incompatible response.',
                request=response.request,
                response=httpx.Response(502, json={'message':'Incompatible Java execution response.'}, request=response.request),
            ) from None
        return result
