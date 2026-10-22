"""Supervised local queue consumer; no automatic checkpoint activation."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import argparse
import json
import os
import time
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.transformations.conversation_models import TransformationTrainingJob
from scripts.run_feedback_job import run_job


@_log_traced('scripts.serve_feedback_jobs.consume_once', level=20)
def consume_once(db):
    occupied=db.scalar(select(TransformationTrainingJob.id).where(TransformationTrainingJob.running_slot==1))
    if occupied is not None:
        from app.transformations.worker_recovery import recover_dead_worker
        if recover_dead_worker(db,occupied):return {'state':'recovered','job_id':occupied}
        return {'state':'occupied','job_id':occupied}
    operators=[int(value.strip()) for value in os.getenv('TRAINING_OPERATOR_IDS','').split(',') if value.strip().isdigit()]
    if not operators:return {'state':'disabled'}
    # Recover approved feedback whose HTTP request ended before scheduling.
    # Training still runs in the existing bounded child process, never FastAPI.
    if os.getenv('FEEDBACK_AUTO_TRAIN', 'false').lower() == 'true':
        from app.models.user import UserModel
        from app.services.feedback_retraining import schedule_safely
        for owner in db.scalars(select(UserModel).where(UserModel.id.in_(operators), UserModel.is_active.is_(True))).all():
            schedule_safely(owner, db)
    job_id=db.scalar(select(TransformationTrainingJob.id).where(TransformationTrainingJob.status=='queued',
        TransformationTrainingJob.user_id.in_(operators)).order_by(TransformationTrainingJob.id).limit(1))
    if job_id is None:return {'state':'idle'}
    try:result=run_job(db,job_id)
    except ValueError:
        # Another service may have claimed this row/slot. Atomic run_job is authoritative.
        _log_exception('scripts.serve_feedback_jobs:31', handled=True)
        db.rollback();return {'state':'claim_conflict','job_id':job_id}
    return {'state':'processed','job':result}


@_log_traced('scripts.serve_feedback_jobs.main', level=20)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true',help='Check the queue once and exit.')
    parser.add_argument('--poll-seconds',type=int,default=10)
    args=parser.parse_args()
    if not 5<=args.poll_seconds<=60:parser.error('Polling interval must be 5..60 seconds.')
    from app.database.session import SessionLocal
    previous=None
    try:
        while True:
            try:
                with SessionLocal() as db:result=consume_once(db)
            except SQLAlchemyError:
                # Do not print database URLs, SQL parameters or private training data.
                _log_exception('scripts.serve_feedback_jobs:49', handled=True)
                result={'state':'database_unavailable','message':'Check database connectivity and migrations.'}
            message=json.dumps(result)
            if message!=previous:print(message,flush=True);previous=message
            if args.once:return
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        _log_exception('scripts.serve_feedback_jobs:56', handled=True)
        print(json.dumps({'state':'stopped','message':'Operator stopped queue consumer.'}),flush=True)


if __name__=='__main__':main()
