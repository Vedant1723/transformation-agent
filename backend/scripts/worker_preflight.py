"""Read-only deployment checks. Never prints connection strings or secrets."""
import json
import os
import re
import sys


def configuration_errors(env):
    errors=[]
    if not env.get('DATABASE_URL','').strip():errors.append('DATABASE_URL must be explicitly configured.')
    if not re.fullmatch(r'[1-9][0-9]*(,[1-9][0-9]*)*',env.get('TRAINING_OPERATOR_IDS','')):
        errors.append('TRAINING_OPERATOR_IDS must list positive authorized user IDs.')
    return errors


def main():
    errors=configuration_errors(os.environ)
    if not errors:
        try:
            import httpx
            from sqlalchemy import inspect,text,select
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            from pathlib import Path
            from app.database.session import engine,SessionLocal
            from app.models.user import UserModel
            from app.transformations.local_model import status
            with engine.connect() as connection:
                tables=inspect(connection).get_table_names()
                if 'transformation_training_jobs' not in tables:errors.append('Training jobs migration missing.')
                versions=connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
                backend=Path(__file__).resolve().parents[1]
                config=Config(str(backend/'alembic.ini'))
                config.set_main_option('script_location',str(backend/'alembic'))
                if set(versions)!=set(ScriptDirectory.from_config(config).get_heads()):errors.append('Database is not at the installed Alembic head.')
            with SessionLocal() as db:
                ids=[int(x) for x in os.environ['TRAINING_OPERATOR_IDS'].split(',')]
                active=set(db.scalars(select(UserModel.id).where(UserModel.id.in_(ids),UserModel.is_active==True)))
                if active!=set(ids):errors.append('One or more configured operators are absent or inactive.')
            from app.transformations.runtime_client import FreeMarkerRuntimeClient
            health=FreeMarkerRuntimeClient().health()
            if health.get('service')!='freemarker-runtime' or health.get('status')!='UP' or 'validation-stop-v1' not in health.get('capabilities',[]):
                errors.append('Compatible FreeMarker runtime required.')
            if not status()['available']:errors.append('Registered model assets or dependencies unavailable.')
        except Exception:
            errors.append('Dependency check failed. Check database configuration, migration and renderer; details suppressed to protect credentials.')
    print(json.dumps({'ready':not errors,'errors':errors,'training_started':False,'model_quality_verified':False}))
    return 1 if errors else 0


if __name__=='__main__':sys.exit(main())
