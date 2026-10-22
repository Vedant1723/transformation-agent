"""Read-only links to private job history, never proof of model activation."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
from sqlalchemy import inspect, select
from app.transformations.conversation_models import TransformationTrainingJob as Job
from app.transformations.conversation_models import TransformationTrainingBundle as Bundle
from app.transformations.conversation_models import TransformationDataset as Dataset


@_log_traced('app.transformations.correction_lineage.correction_lineage', level=10)
def correction_lineage(db,user_id,session_id,revision_id,fingerprint):
    result={'status':'not_found_in_recent_jobs','jobs':[], 'history_limit':100,
            'active_model_learning_confirmed':False}
    if not inspect(db.get_bind()).has_table(Job.__tablename__):
        return {**result,'status':'job_schema_missing'}
    rows=db.execute(select(Job,Bundle,Dataset).join(Bundle,Job.bundle_id==Bundle.id)
        .join(Dataset,Bundle.dataset_id==Dataset.id).where(Job.user_id==user_id,
            Bundle.user_id==user_id,Dataset.user_id==user_id)
        .order_by(Job.id.desc()).limit(100)).all()
    for job,bundle,dataset in rows:
        if job.settings.get('bundle_sha256')!=bundle.bundle.get('content_sha256'):
            continue
        if bundle.bundle.get('dataset_sha256')!=dataset.manifest.get('content_sha256'):
            continue
        for record in dataset.manifest.get('records',[]):
            provenance=record.get('provenance',{})
            if (provenance.get('session_id'),provenance.get('revision'))!=(session_id,revision_id):continue
            prepared=next((e for e in bundle.bundle.get('examples',[]) if e.get('id')==record.get('id')),None)
            if prepared is None or prepared.get('split')!=record.get('split'):continue
            exact=bool(fingerprint and provenance.get('fingerprint')==fingerprint)
            steps=job.result.get('steps')
            completed=job.status=='completed' and type(steps) is int and steps>0
            usage=('candidate_training_completed' if record['split']=='train' else 'evaluation_only_completed') if completed else job.status
            if job.status=='completed' and not completed:usage='completion_evidence_incomplete'
            result['jobs'].append({'job_id':job.id,'bundle_id':bundle.id,'dataset_id':dataset.id,
                'status':job.status,'usage':usage,'split':record['split'],'matches_current_review':exact})
            break
    exact_jobs=[j for j in result['jobs'] if j['matches_current_review']]
    if exact_jobs:result['status']=exact_jobs[0]['usage']
    elif result['jobs']:result['status']='older_review_only'
    return result
