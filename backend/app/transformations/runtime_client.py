from app.core.observability import traced as _log_traced, exception_event as _log_exception
from typing import Any, Dict

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
    ) -> Dict[str, Any]:

        response = httpx.post(
            self.base_url + self.settings.transform_path,
            json={
                "template": runtime_template(template, direction),
                "input": input_payload,
                "direction": direction,
                "additionalProperties": additionalProperties or {},
                "headers": headers or {},
            },
            headers=self.settings.headers(),
            timeout=self.settings.timeout_seconds,
        )

        response.raise_for_status()

        try:
            result = response.json()
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
