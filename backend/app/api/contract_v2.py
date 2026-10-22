"""Versioned transport adapter. Business logic and v1 remain unchanged."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

ERROR_CODES = {400:'BAD_REQUEST',401:'UNAUTHORIZED',403:'FORBIDDEN',404:'NOT_FOUND',
               405:'METHOD_NOT_ALLOWED',409:'CONFLICT',422:'VALIDATION_ERROR',429:'RATE_LIMITED',503:'SERVICE_UNAVAILABLE',504:'TIMEOUT'}


@_log_traced('app.api.contract_v2.envelope', level=10)
def envelope(payload, status=200):
    ok = status < 400
    if not ok:
        detail = payload.get('detail', payload) if isinstance(payload, dict) else payload
        return dict(st=False, msg='failure', msgId=ERROR_CODES.get(status, 'INTERNAL_ERROR'), data={'detail':detail})
    if isinstance(payload, dict) and isinstance(payload.get('success'), bool):
        ok = payload['success']
        data = payload.get('data', {})
        extra = {k:v for k,v in payload.items() if k not in ('success','data')}
        if extra:
            # Keep metadata without silently dropping legacy next_action/message fields.
            data = {**data, '_meta':extra} if isinstance(data,dict) else {'items':data, '_meta':extra}
    else:
        data = payload
    if not isinstance(data, (dict, list)):
        data = {'value':data}
    return dict(st=ok, msg='success' if ok else 'failure',
                msgId=('CREATED' if status==201 else 'ACCEPTED' if status==202 else 'SUCCESS') if ok else 'OPERATION_FAILED', data=data)


class ContractRoute(APIRoute):
    @_log_traced('app.api.contract_v2.ContractRoute.get_route_handler', level=10)
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request: Request):
            response = await original(request)
            if response.headers.get('content-type','').startswith('application/json') and hasattr(response,'body'):
                body = envelope(json.loads(response.body), response.status_code)
                wrapped = JSONResponse(body, status_code=response.status_code, background=response.background)
                wrapped.raw_headers = [(k,v) for k,v in response.raw_headers if k.lower() not in (b'content-length',b'content-type')] + wrapped.raw_headers
                return wrapped
            return response
        return handler


@_log_traced('app.api.contract_v2.create_contract_app', level=10)
def create_contract_app(routers):
    api = FastAPI(title='Biller AI backend API', version='2.0.0',
                  description='Stable response envelope. Existing business workflows; no automatic model activation.')
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            api.router.add_api_route(route.path.removeprefix('/api/v1'), route.endpoint,
                methods=route.methods, response_model=route.response_model, status_code=route.status_code,
                tags=route.tags, summary=route.summary, description=route.description,
                dependencies=route.dependencies, responses=route.responses, name=route.name,
                response_class=route.response_class, response_model_exclude_none=route.response_model_exclude_none,
                route_class_override=ContractRoute)

    @api.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(envelope({'detail':exc.detail}, exc.status_code), status_code=exc.status_code, headers=exc.headers)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo submitted passwords, tokens, payloads or Pydantic ctx objects.
        errors = [{'loc':list(e['loc']), 'type':e['type'], 'msg':'Invalid value.'} for e in exc.errors()]
        return JSONResponse(envelope({'detail':errors},422), status_code=422)

    @api.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.getLogger(__name__).error('Unhandled v2 API error: %s', type(exc).__name__)
        return JSONResponse(envelope({'detail':'Internal server error. Contact the service operator.'},500), status_code=500)

    @api.get('/health', tags=['Health'])
    def health():
        return envelope({'status':'UP','service':'ai-control-room'})

    original_openapi = api.openapi
    def openapi():
        if api.openapi_schema:
            return api.openapi_schema
        schema = original_openapi()
        for path, methods in schema['paths'].items():
            for method, operation in methods.items():
                if method not in ('get','post','put','patch','delete','options','head'):
                    continue
                for code in ('400','401','403','404','409','422','500','503'):
                    operation['responses'].setdefault(code, {'description':ERROR_CODES.get(int(code),'INTERNAL_ERROR')})
                for response in operation['responses'].values():
                    response['content']={'application/json':{'schema':{'$ref':'#/components/schemas/ApiEnvelope'}}}
        schema.setdefault('components',{}).setdefault('schemas',{})['ApiEnvelope']={
            'type':'object','required':['st','msg','msgId','data'],'additionalProperties':False,
            'properties':{'st':{'type':'boolean'},'msg':{'type':'string','enum':['success','failure']},
                          'msgId':{'type':'string'},'data':{'anyOf':[{'type':'object','additionalProperties':True},{'type':'array','items':{}}]}}}
        # External identity comes from the gateway, not the legacy bearer dependency.
        schema['components']['securitySchemes']={'GatewayKey':{'type':'apiKey','in':'header','name':'X-Gateway-Key'},
                                                 'GatewayIdentity':{'type':'apiKey','in':'header','name':'X-Authenticated-User'}}
        for path, methods in schema['paths'].items():
            for method, operation in methods.items():
                if method in ('get','post','put','patch','delete'):
                    operation['security']=[] if path=='/health' else [{'GatewayKey':[],'GatewayIdentity':[]}]
        api.openapi_schema = schema
        return schema
    api.openapi = openapi
    return api
