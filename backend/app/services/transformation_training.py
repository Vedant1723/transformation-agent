from app.core.observability import traced as _log_traced, exception_event as _log_exception
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.user import UserModel
from app.transformations.conversation_models import TransformationTrainingBundle, TransformationDataset
from app.services.transformation_datasets import version, policy, benchmark, reviewed
from app.transformations.dataset_policy import related
from app.transformations.training_bundle import compile_bundle
from app.transformations.dataset import digest



@_log_traced('app.services.transformation_training.authorized_manifest', level=20)
def authorized_manifest(dataset_id, user, db):
    manifest = version(dataset_id, user, db)['data']['manifest']
    state = policy(db, user)
    if not state.get('benchmark_id') or manifest.get('benchmark_id') != state['benchmark_id']:
        raise HTTPException(422, 'Freeze an evaluation benchmark, then create a new dataset export with independent training examples.')
    seeds = benchmark(db, user, state)
    versions = db.scalars(select(TransformationDataset).where(TransformationDataset.user_id == user.id)).all()
    history = [r for v in versions for r in v.manifest['records']]
    rows = [{'key': f'prior:{i}', 'session_id': r['provenance']['session_id'],
        'lineage_sessions': r['provenance'].get('lineage_sessions', []), 'example': r['example']} for i, r in enumerate(history)]
    connected = related(rows + reviewed(db, user), seeds)
    if any(f'prior:{i}' in connected and r['split'] == 'train' for i, r in enumerate(history)):
        raise HTTPException(409, 'Benchmark is connected to exported training data. Preparation blocked for leakage review.')
    return manifest


class Prepare(BaseModel):
    dataset_id: int
    max_merges: int = Field(default=32, ge=0, le=64)
    max_sequence_tokens: int = Field(default=8192, ge=128, le=32768)


class PrepareExisting(BaseModel):
    dataset_id: int = Field(gt=0)


@_log_traced('app.services.transformation_training.readiness', level=20)
def readiness(user:UserModel,db:Session):
    """Read-only infrastructure checks; not an accuracy or worker-liveness claim."""
    import os
    import httpx
    from sqlalchemy import inspect
    from sqlalchemy.exc import SQLAlchemyError
    from app.transformations.local_model import status
    checks=[]
    try:
        schema=inspect(db.get_bind()).has_table('transformation_training_jobs')
        checks.append({'name':'job_schema','ready':schema,'message':'Job table exists.' if schema else 'Back up the database, then run python -m alembic upgrade head from backend.'})
    except SQLAlchemyError:
        _log_exception('app.services.transformation_training:51', handled=True)
        checks.append({'name':'job_schema','ready':False,'message':'Database check failed; verify connectivity.'})
    validation_stops=False
    try:
        from app.transformations.runtime_client import FreeMarkerRuntimeClient
        health=FreeMarkerRuntimeClient().health(timeout=2)
        renderer=isinstance(health,dict) and health.get('status')=='UP' and health.get('service')=='freemarker-runtime'
        capabilities=health.get('capabilities') if isinstance(health,dict) else None
        validation_stops=renderer and isinstance(capabilities,list) and 'validation-stop-v1' in capabilities
    except (httpx.HTTPError,ValueError):_log_exception('app.services.transformation_training:60', handled=True); renderer=False
    checks.append({'name':'renderer','ready':renderer,'message':'Java execution service health verified.' if renderer else 'Check the configured Java execution service; its health response must identify freemarker-runtime as UP.'})
    checks.append({'name':'validation_rejections','ready':validation_stops,'message':'Runtime advertises typed validation-stop support.' if validation_stops else 'Rebuild and restart the FreeMarker runtime: expected-rejection tests require validation-stop-v1. A health response alone is not sufficient.'})
    model=status()
    checks.append({'name':'model_files','ready':model['available'],'message':'Model files and PyTorch are present; inference is not tested by this check.' if model['available'] else 'Restore the registered model bundle and install training dependencies.'})
    allowed=str(user.id) in {value.strip() for value in os.getenv('TRAINING_OPERATOR_IDS','').split(',')}
    checks.append({'name':'operator_access','ready':allowed,'message':'This user may queue training.' if allowed else 'Ask an administrator to configure training-operator access.'})
    return {'success':True,'data':{'checks':checks,'prerequisites_ready':all(item['ready'] for item in checks),
        'worker_liveness':'not_checked','model_quality':'not_checked','active_model_changed':False}}


@_log_traced('app.services.transformation_training.existing_model_assets', level=20)
def existing_model_assets():
    import json
    import hashlib
    from app.transformations.local_model import ROOT,RUN,CHECKPOINT
    root=ROOT/'model-runs'/RUN
    checkpoint=root/CHECKPOINT
    bundle_path=root/'bundle.json'
    if checkpoint.stat().st_size>100_000_000 or bundle_path.stat().st_size>20_000_000:
        raise ValueError('Unexpected model artifact size.')
    bundle=json.loads(bundle_path.read_text(encoding='utf-8'))
    if digest({k:v for k,v in bundle.items() if k!='content_sha256'})!=bundle['content_sha256']:
        raise ValueError('Existing model bundle integrity failed.')
    # The current registered TinyTransformer uses context_length=1024.
    return bundle['tokenizer'],{'checkpoint':RUN+'/'+CHECKPOINT,
        'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        'bundle_sha256':bundle['content_sha256'],'context_length':1024}


@_log_traced('app.services.transformation_training.prepare_existing', level=20)
def prepare_existing(request:PrepareExisting,user:UserModel,db:Session):
    manifest=authorized_manifest(request.dataset_id,user,db)
    try:
        tokenizer,parent=existing_model_assets()
        bundle=compile_bundle(manifest,max_sequence_tokens=parent['context_length'],frozen_tokenizer=tokenizer,normalize_model_prompt=True)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        _log_exception('app.services.transformation_training:94', handled=True)
        raise HTTPException(422,'Existing-model preparation failed: '+str(exc)) from exc
    bundle['parent_model']=parent
    bundle['preparation_only']=True
    bundle['content_sha256']=digest({k:v for k,v in bundle.items() if k!='content_sha256'})
    db.expire_all();authorized_manifest(request.dataset_id,user,db)
    row=TransformationTrainingBundle(user_id=user.id,dataset_id=request.dataset_id,bundle=bundle)
    db.add(row);db.commit();db.refresh(row)
    return {'success':True,'data':{'id':row.id,'dataset_id':row.dataset_id,'bundle':row.bundle}}


@_log_traced('app.services.transformation_training.prepare', level=20)
def prepare(request: Prepare, user: UserModel, db: Session):
    manifest = authorized_manifest(request.dataset_id, user, db)
    try:
        bundle = compile_bundle(manifest, request.max_merges, request.max_sequence_tokens)
    except (ValueError, KeyError, TypeError) as exc:
        _log_exception('app.services.transformation_training:109', handled=True)
        raise HTTPException(422, str(exc)) from exc
    db.expire_all()
    authorized_manifest(request.dataset_id, user, db)
    row = TransformationTrainingBundle(user_id=user.id, dataset_id=request.dataset_id, bundle=bundle)
    db.add(row); db.commit(); db.refresh(row)
    return {'success': True, 'data': {'id': row.id, 'dataset_id': row.dataset_id, 'bundle': row.bundle}}


@_log_traced('app.services.transformation_training.bundles', level=20)
def bundles(user: UserModel, db: Session):
    rows = db.scalars(select(TransformationTrainingBundle).where(TransformationTrainingBundle.user_id == user.id)
        .order_by(TransformationTrainingBundle.id.desc()).limit(100)).all()
    return {'success': True, 'data': [{'id': r.id, 'dataset_id': r.dataset_id,
        'counts': r.bundle['counts'], 'vocab_size': r.bundle['tokenizer']['vocab_size'],
        'existing_model_bundle':bool(r.bundle.get('parent_model') and r.bundle.get('preparation_only')),
        'content_sha256': r.bundle['content_sha256']} for r in rows]}


@_log_traced('app.services.transformation_training.download', level=20)
def download(bundle_id: int, user: UserModel, db: Session):
    row = db.scalar(select(TransformationTrainingBundle).where(TransformationTrainingBundle.id == bundle_id,
        TransformationTrainingBundle.user_id == user.id))
    if not row:
        raise HTTPException(404, 'Training bundle not found.')
    authorized_manifest(row.dataset_id, user, db)
    return {'success': True, 'data': {'id': row.id, 'dataset_id': row.dataset_id, 'bundle': row.bundle}}
