"""Private, opt-in training queue. Workers run outside the API process."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import os
from fastapi import HTTPException
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,update,inspect
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from sqlalchemy.orm import Session
from app.models.user import UserModel
from app.transformations.conversation_models import TransformationTrainingJob
from app.services.transformation_training import download
from app.transformations.release_readiness import release_readiness

@_log_traced('app.services.transformation_jobs.require_job_schema', level=20)
def require_job_schema(user:UserModel,db:Session):
    try:
        present=inspect(db.get_bind()).has_table('transformation_training_jobs')
    except SQLAlchemyError as exc:
        _log_exception('app.services.transformation_jobs:16', handled=True)
        raise HTTPException(503,'Training database unavailable. Check database connectivity.') from exc
    if not present:
        raise HTTPException(503,'Training-job schema is missing. Back up the database, then run python -m alembic upgrade head from backend.')




@_log_traced('app.services.transformation_jobs.operator', level=20)
def operator(user):
    if str(user.id) not in {x.strip() for x in os.getenv('TRAINING_OPERATOR_IDS','').split(',')}:
        raise HTTPException(403,'Training requires configured operator access.')


class Queue(BaseModel):
    model_config=ConfigDict(extra='forbid')
    bundle_id:int=Field(gt=0)
    request_key:str=Field(min_length=8,max_length=100)
    steps:int=Field(default=100,ge=1,le=500)


@_log_traced('app.services.transformation_jobs.view', level=20)
def view(row):
    return {'id':row.id,'bundle_id':row.bundle_id,'status':row.status,'settings':row.settings,
            'result':row.result,'active_model_changed':False,
            'release_readiness':release_readiness(row.status,row.result)}


@_log_traced('app.services.transformation_jobs.enqueue', level=20)
def enqueue(request:Queue,user:UserModel,db:Session):
    operator(user)
    previous=db.scalar(select(TransformationTrainingJob).where(TransformationTrainingJob.user_id==user.id,
        TransformationTrainingJob.request_key==request.request_key))
    if previous:
        if previous.bundle_id!=request.bundle_id or previous.settings['steps']!=request.steps:
            raise HTTPException(409,'Request key already used with different settings.')
        return {'success':True,'data':view(previous)}
    bundle=download(request.bundle_id,user,db)['data']['bundle']
    if not bundle.get('parent_model') or not bundle.get('preparation_only'):
        raise HTTPException(422,'Prepare an existing-model bundle first.')
    if len(bundle['examples'])>20:raise HTTPException(422,'Pilot jobs accept at most 20 reviewed examples.')
    row=TransformationTrainingJob(user_id=user.id,bundle_id=request.bundle_id,request_key=request.request_key,
        status='queued',settings={'steps':request.steps,'bundle_sha256':bundle['content_sha256']},result={})
    db.add(row)
    try:db.commit();db.refresh(row)
    except IntegrityError:
        _log_exception('app.services.transformation_jobs:58', handled=True)
        db.rollback();raise HTTPException(409,'Concurrent submission. Retry with the same request key.')
    return {'success':True,'data':view(row)}


@_log_traced('app.services.transformation_jobs.status', level=20)
def status(job_id:int,user:UserModel,db:Session):
    row=db.scalar(select(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id,TransformationTrainingJob.user_id==user.id))
    if row is None:raise HTTPException(404,'Training job not found.')
    return {'success':True,'data':view(row)}


@_log_traced('app.services.transformation_jobs.list_jobs', level=20)
def list_jobs(user:UserModel,db:Session):
    rows=db.scalars(select(TransformationTrainingJob).where(TransformationTrainingJob.user_id==user.id)
        .order_by(TransformationTrainingJob.id.desc()).limit(50)).all()
    return {'success':True,'data':[view(row) for row in rows]}


@_log_traced('app.services.transformation_jobs.candidate_report', level=20)
def candidate_report(job_id:int,user:UserModel,db:Session):
    row=db.scalar(select(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id,TransformationTrainingJob.user_id==user.id))
    if row is None:raise HTTPException(404,'Training job not found.')
    if row.status!='completed':raise HTTPException(409,'A completed candidate job is required.')
    bundle=download(row.bundle_id,user,db)['data']['bundle']
    from app.transformations.dataset import digest
    if digest({k:v for k,v in bundle.items() if k!='content_sha256'})!=row.settings['bundle_sha256']:
        raise HTTPException(409,'Prepared bundle integrity check failed.')
    from app.transformations.candidate_report import read_candidate_report
    from app.transformations.local_model import ROOT
    try:report=read_candidate_report(ROOT,row,bundle)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        _log_exception('app.services.transformation_jobs:86', handled=True)
        raise HTTPException(409,'Candidate report unavailable or integrity checks failed. Older jobs need a new run to produce verified evidence.')
    return {'success':True,'data':report}


@_log_traced('app.services.transformation_jobs.cancel', level=20)
def cancel(job_id:int,user:UserModel,db:Session):
    row=db.scalar(select(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id,TransformationTrainingJob.user_id==user.id))
    if row is None:raise HTTPException(404,'Training job not found.')
    if row.status=='cancelled':return {'success':True,'data':view(row)}
    changed=db.execute(update(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id,
        TransformationTrainingJob.user_id==user.id,TransformationTrainingJob.status=='queued').values(
        status='cancelled',result={'reason':'Cancelled by owner before execution.'}),execution_options={'synchronize_session':False})
    if changed.rowcount!=1:
        db.rollback();raise HTTPException(409,'Only queued jobs can be cancelled; this job may already be running.')
    db.commit();db.refresh(row)
    return {'success':True,'data':view(row)}
