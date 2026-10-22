"""Reviewed-output regression scoring, not a trained-model evaluation claim."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import httpx
from lxml import etree
from app.schemas.transformations import TransformationChatRequest
from app.transformations.workbench import normalize, generate
from app.transformations.runtime_client import FreeMarkerRuntimeClient
from app.transformations.dataset import digest


@_log_traced('app.transformations.scoring.canonical', level=10)
def canonical(output, fmt):
    if fmt == 'JSON':
        from app.transformations.json_validation import strict_json
        return json.dumps(strict_json(output), sort_keys=True, ensure_ascii=False, allow_nan=False)
    if fmt == 'XML':
        if '<!DOCTYPE' in output.upper():
            raise ValueError('DOCTYPE is not allowed')
        root = etree.fromstring(output.encode(), etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True))
        return etree.tostring(root, method='c14n')
    return normalize(output, 'ISO')


@_log_traced('app.transformations.scoring.score_case', level=10)
def score_case(record, mode):
    example = record['example']
    context = example['context']
    result = {'id': record['id'], 'expected': example['test']['output'], 'actual': '',
        'status': 'failed', 'stage': 'generation', 'error': '', 'template': example['template'],
        'context': context}
    try:
        if mode == 'regenerate':
            result['template'] = generate(TransformationChatRequest(**{**context, 'use_learned': False}))['template']
        result['stage'] = 'input'
        payload = context['source']['payload']
        normalized = normalize(payload, context['source']['format'])
        if context['source']['format'] != 'XML' or 'JsonUtils.getJsonAsMap(input)' in result['template']:
            payload = normalized
        result['stage'] = 'runtime'
        rendered = FreeMarkerRuntimeClient().execute(result['template'], payload, context['direction'],
            context.get('additionalProperties'), context.get('headers'))
        result['actual'] = rendered.get('output', '')
        if not rendered.get('success'):
            raise ValueError(rendered.get('error') or rendered.get('message') or 'Rendering failed')
        result['stage'] = 'comparison'
        fmt = context['target']['format']
        result['status'] = 'passed' if canonical(result['actual'], fmt) == canonical(result['expected'], fmt) else 'mismatch'
    except httpx.RequestError:
        _log_exception('app.transformations.scoring:46', handled=True)
        result.update(status='infrastructure_error', error='Java renderer unavailable or timed out')
    except httpx.HTTPStatusError as exc:
        _log_exception('app.transformations.scoring:48', handled=True)
        message = f'Renderer HTTP {exc.response.status_code}'
        if exc.response.status_code < 500:
            try:
                detail = exc.response.json()
                if isinstance(detail, dict):
                    message = str(detail.get('error') or detail.get('message') or message)
                    if exc.response.status_code == 400 and detail.get('error_kind') == 'validation_stop':
                        result['error_kind'] = 'validation_stop'
                        result['validation_message'] = detail.get('validation_message', '')
            except ValueError:
                _log_exception('app.transformations.scoring:58', handled=True)
                pass
        result.update(status='infrastructure_error' if exc.response.status_code >= 500 else 'failed', error=message)
    except (ValueError, TypeError, KeyError, etree.XMLSyntaxError) as exc:
        _log_exception('app.transformations.scoring:61', handled=True)
        result['error'] = str(exc)
    result['template_sha256'] = digest(result['template'])
    return result
