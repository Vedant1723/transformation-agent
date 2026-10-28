"""Isolated anonymous preview API. No database, execution, model or learning access."""
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from app.schemas.transformations import TransformationChatRequest
from app.transformations.workbench import generate
from app.transformations.payload_generator import generate_payload

PREFIX = '/transformation-agent'
app = FastAPI(title='Transformation Agent - anonymous preview',
              docs_url=PREFIX + '/docs', openapi_url=PREFIX + '/openapi.json', redoc_url=None)


def reply(data, status=200, code='SUCCESS'):
    return JSONResponse({'st': status < 400, 'msg': 'success' if status < 400 else 'failure',
                         'msgId': code, 'data': data}, status_code=status)


def bounded(value, depth=0):
    if depth > 12:
        raise ValueError('Maximum input nesting is 12 levels.')
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError('Maximum 100 fields per object.')
        for child in value.values():
            bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 20:
            raise ValueError('Maximum 20 sample items per list.')
        for child in value:
            bounded(child, depth + 1)


async def body(request):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 32768:
            raise ValueError('Maximum request size is 32 KiB.')
    data = json.loads(chunks)
    if not isinstance(data, dict):
        raise ValueError('Request must be a JSON object.')
    bounded(data)
    return data


@app.get(PREFIX + '/health')
@app.get(PREFIX + '/ready')
def health():
    return reply({'status': 'UP', 'mode': 'anonymous-preview', 'persistent': False})


@app.post(PREFIX + '/api/v2/transformations/generate')
async def preview(request: Request):
    try:
        payload = TransformationChatRequest.model_validate(await body(request))
        if payload.use_learned:
            raise ValueError('Learned data is not available in anonymous preview.')
        # JSON strings are bounded after parsing too. XML is not accepted in this
        # public preview until parser/resource controls receive separate review.
        for item in (payload.source, payload.target):
            if item.format.upper() != 'JSON':
                raise ValueError('Anonymous preview supports JSON source/target only.')
            if isinstance(item.payload, str):
                item.payload = json.loads(item.payload)
            bounded(item.payload)
        result = await run_in_threadpool(generate, payload)
        result.update(verified=False, persisted=False, mode='anonymous-preview')
        return reply(result)
    except (ValueError, ValidationError, RecursionError):
        return reply({'message': 'Invalid or unsupported preview input. Use JSON source/target, no learned data, nesting <=12 and request <=32 KiB.'}, 422, 'INVALID_INPUT')


@app.post(PREFIX + '/api/v2/transformations/tools')
async def payload_preview(request: Request):
    try:
        data = await body(request)
        if data.get('action') != 'generate_payload':
            raise ValueError('Only generate_payload is available.')
        template = data.get('template')
        if not isinstance(template, str) or not 0 < len(template) <= 4096:
            raise ValueError('Template must contain 1-4096 characters.')
        if data.get('source_format', 'JSON') != 'JSON' or data.get('direction', 'REQUEST') not in ('REQUEST', 'RESPONSE'):
            raise ValueError('Unsupported preview format/direction.')
        result = await run_in_threadpool(generate_payload, template, 'JSON', data.get('direction', 'REQUEST'))
        return reply(result)
    except (ValueError, RecursionError):
        return reply({'message': 'Use action generate_payload, JSON format and a template of at most 4096 characters.'}, 422, 'INVALID_INPUT')
