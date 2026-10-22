"""Dependency readiness without credentials, SQL errors or payload disclosure."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import os
from sqlalchemy import inspect, text
from app.database.session import engine
from app.transformations.runtime_client import FreeMarkerRuntimeClient
from app.transformations.local_model import status


@_log_traced('app.services.readiness.readiness', level=20)
def readiness():
    checks = {'database': False, 'schema': False, 'java_execution': False}
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
            checks['database'] = True
            tables = set(inspect(connection).get_table_names())
            checks['schema'] = {'users', 'knowledge_items', 'transformation_sessions',
                'transformation_datasets', 'transformation_training_bundles',
                'transformation_training_jobs'}.issubset(tables)
    except Exception:
        _log_exception('app.services.readiness:19', handled=True)
        pass
    try:
        health = FreeMarkerRuntimeClient().health(timeout=3)
        checks['java_execution'] = (isinstance(health, dict) and health.get('status') == 'UP'
            and health.get('service') == 'freemarker-runtime'
            and 'validation-stop-v1' in health.get('capabilities', []) and health.get('xmlModel') == 'dom-v1')
    except Exception:
        _log_exception('app.services.readiness:26', handled=True)
        pass
    if os.getenv('FEEDBACK_AUTO_TRAIN', 'false').lower() == 'true':
        checks['model_artifacts'] = status()['available']
    ready = all(checks.values())
    return {'st': ready, 'msg': 'success' if ready else 'failure',
            'msgId': 'SUCCESS' if ready else 'SERVICE_UNAVAILABLE',
            'data': {'ready': ready, 'checks': checks, 'worker_liveness': 'not_checked',
                     'scope': 'Dependency checks, not model quality or full execution acceptance.'}}
