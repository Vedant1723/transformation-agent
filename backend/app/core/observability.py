"""Structured, payload-free operational logging to stderr."""
import contextvars
import functools
import inspect
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

correlation_id = contextvars.ContextVar('correlation_id', default='')
logger = logging.getLogger('transformation_agent')


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname, 'event': record.getMessage(),
            'correlation_id': correlation_id.get() or os.getenv('TRANSFORMATION_TRACE_ID', ''),
            **getattr(record, 'safe_fields', {})}, ensure_ascii=True)


def configure_logging():
    level = os.getenv('LOG_LEVEL', 'INFO').upper()
    if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
        raise ValueError('LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL.')
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def event(name, level=logging.INFO, **fields):
    # Never accept payloads, arbitrary objects, exception messages or credentials.
    allowed = {'operation', 'duration_ms', 'status_code', 'method', 'route', 'exception_type',
               'frames', 'job_id', 'passed', 'stage', 'steps', 'outcome'}
    logger.log(level, name, extra={'safe_fields': {k: v for k, v in fields.items() if k in allowed}})


def exception_event(operation, exc=None, handled=False):
    exc = exc if exc is not None else sys.exception()
    frames = []
    tb = getattr(exc, '__traceback__', None)
    while tb is not None:
        # File name/line/function only; never source lines, locals or exception text.
        frames.append({'file': os.path.basename(tb.tb_frame.f_code.co_filename),
                       'line': tb.tb_lineno, 'function': tb.tb_frame.f_code.co_name})
        tb = tb.tb_next
    event('exception.handled' if handled else 'operation.failed',
          logging.WARNING if handled else logging.ERROR, operation=operation,
          exception_type=type(exc).__name__, frames=frames[-8:])


def traced(operation, level=logging.DEBUG):
    """Preserve signatures and behavior; never log arguments or returned objects."""
    def decorate(function):
        signature = inspect.signature(function)
        has_job_id = 'job_id' in signature.parameters
        def start():
            configure_logging()
            event('operation.started', level, operation=operation)
            return time.monotonic()

        def finish(started, result):
            fields = {'operation': operation, 'duration_ms': round((time.monotonic()-started)*1000, 2)}
            if isinstance(result, dict):
                data = result.get('data', result)
                if isinstance(data, dict) and type(data.get('passed')) is bool:
                    fields['passed'] = data['passed']
                if isinstance(data, dict) and data.get('status') in ('queued', 'running', 'completed', 'failed', 'disabled', 'preparation_blocked', 'waiting_for_benchmark'):
                    fields['outcome'] = data['status']
            event('operation.completed', level, **fields)

        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def asynchronous(*args, **kwargs):
                started = start()
                try:
                    result = await function(*args, **kwargs)
                    finish(started, result)
                    return result
                except Exception as exc:
                    exception_event(operation, exc)
                    raise
            return asynchronous

        @functools.wraps(function)
        def synchronous(*args, **kwargs):
            started = start()
            token = None
            try:
                if has_job_id:
                    bound = signature.bind_partial(*args, **kwargs)
                    job_id = bound.arguments.get('job_id')
                    if type(job_id) is int:
                        token = correlation_id.set('job-' + str(job_id))
                        event('job.step', level, operation=operation, job_id=job_id)
                result = function(*args, **kwargs)
                finish(started, result)
                return result
            except Exception as exc:
                exception_event(operation, exc)
                raise
            finally:
                if token is not None: correlation_id.reset(token)
        return synchronous
    return decorate


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        token = correlation_id.set(uuid4().hex)
        started, status = time.monotonic(), 500
        # Do not log arbitrary paths or query strings: either may contain secrets.
        known = {'/health', '/ready', '/api/v2/health', '/api/v2/docs', '/api/v2/openapi.json'}
        known.update('/api/v2/transformations/' + action for action in ('generate', 'test', 'tools', 'feedback', 'model'))
        route = scope.get('path') if scope.get('path') in known else 'unmatched'
        event('request.started', method=scope['method'], route=route)

        async def wrapped_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message = {**message, 'headers': [(k, v) for k, v in message.get('headers', []) if k.lower() != b'x-request-id'] +
                           [(b'x-request-id', correlation_id.get().encode('ascii'))]}
            await send(message)
        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as exc:
            exception_event('http.request', exc)
            raise
        finally:
            event('request.completed', logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO,
                  method=scope['method'], route=route, status_code=status,
                  duration_ms=round((time.monotonic()-started)*1000, 2))
            correlation_id.reset(token)


def child_environment():
    return {**os.environ, 'TRANSFORMATION_TRACE_ID': correlation_id.get() or os.getenv('TRANSFORMATION_TRACE_ID', '')}
