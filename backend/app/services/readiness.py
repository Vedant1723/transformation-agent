"""Dependency readiness without credentials, SQL errors or payload disclosure."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import os
from sqlalchemy import inspect, text
from app.database.session import engine
from app.transformations.local_model import status


@_log_traced('app.services.readiness.readiness', level=20)
def readiness():
    checks = {'database': False, 'schema': False}
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
    if os.getenv('FEEDBACK_AUTO_TRAIN', 'false').lower() == 'true':
        checks['model_artifacts'] = status()['available']
    ready = all(checks.values())
    return {'st': ready, 'msg': 'success' if ready else 'failure',
            'msgId': 'SUCCESS' if ready else 'SERVICE_UNAVAILABLE',
            'data': {'ready': ready, 'checks': checks, 'worker_liveness': 'not_checked',
                     'java_execution': 'not_checked',
                     'scope': 'Database/schema and optional model files only. Java execution is checked on actual transformation calls.'}}
