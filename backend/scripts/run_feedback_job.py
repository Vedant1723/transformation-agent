"""Run one queued private feedback job outside FastAPI; never activate weights."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from app.transformations.conversation_models import TransformationTrainingJob
from app.services.transformation_jobs import operator
from app.services.transformation_training import download,authorized_manifest
from app.models.user import UserModel
from app.transformations.dataset import digest
from app.transformations.feedback_process import bounded_train,CleanupUncertain


@_log_traced('scripts.run_feedback_job.train', level=20)
def train(bundle,manifest,steps,job_id):
    from app.core.observability import event
    event('training.phase', job_id=job_id, stage='load_checkpoint', steps=steps)
    import torch
    from app.transformations.local_model import ROOT,RUN,CHECKPOINT
    from app.transformations.tiny_model import TinyTransformer,causal_loss,generate_template
    from app.transformations.training_bundle import compile_bundle,pair
    from app.transformations.scoring import score_case
    parent=bundle['parent_model'];source=ROOT/'model-runs'/RUN
    checkpoint=source/CHECKPOINT
    if parent['checkpoint']!=RUN+'/'+CHECKPOINT or hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=parent['checkpoint_sha256']:
        raise ValueError('Parent checkpoint changed; prepare again.')
    saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
    reference=json.loads((source/'bundle.json').read_text(encoding='utf-8'))
    if digest({k:v for k,v in reference.items() if k!='content_sha256'})!=saved['bundle_sha256']:
        raise ValueError('Replay bundle integrity check failed.')
    if saved['tokenizer']!=bundle['tokenizer'] or saved['config']['context_length']!=parent['context_length'] or saved['bundle_sha256']!=parent['bundle_sha256']:
        raise ValueError('Parent tokenizer/configuration mismatch.')
    prompt_contract=bundle.get('settings',{}).get('prompt_contract')
    if prompt_contract not in (None,'empty-optionals-v1'):raise ValueError('Unknown model prompt contract.')
    normalize_prompt=prompt_contract=='empty-optionals-v1'
    rebuilt=compile_bundle(manifest,max_sequence_tokens=parent['context_length'],frozen_tokenizer=saved['tokenizer'],normalize_model_prompt=normalize_prompt)
    if rebuilt['examples']!=bundle['examples']:raise ValueError('Prepared examples differ from authorized data.')
    torch.manual_seed(23);torch.set_num_threads(2)
    device='cuda' if torch.cuda.is_available() else 'cpu'
    if device=='cuda':torch.cuda.set_per_process_memory_fraction(.65)
    model=TinyTransformer(**saved['config']).to(device);model.load_state_dict(saved['model'])
    optimizer=torch.optim.AdamW(model.parameters(),lr=.00005)
    optimizer.load_state_dict(saved['optimizer'])
    for group in optimizer.param_groups:group['lr']=.00001
    for state in optimizer.state.values():
        for key,value in state.items():
            if torch.is_tensor(value) and key!='step':state[key]=value.to(device)
    for record in manifest['records']:
        if score_case(record,'replay')['status']!='passed':raise ValueError('Reference no longer passes execution.')
        from app.transformations.correction_cases import replay_cases
        example=record['example']
        if not all(case['passed'] for case in replay_cases(example['context'],example['template'],example.get('validation_cases',[]))):
            raise ValueError('Reference correction scenario no longer passes execution.')
    def evaluate():
        results=[]
        for record in manifest['records']:
            prediction=generate_template(model,pair(record,normalize_prompt)['prompt'],saved['tokenizer'],device,max_new_tokens=850)
            case=copy.deepcopy(record);case['example']['template']=prediction['template']
            evidence=score_case(case,'replay')
            if evidence['status']=='infrastructure_error':raise ValueError('Renderer unavailable during evaluation.')
            scenario_results=replay_cases(case['example']['context'],prediction['template'],case['example'].get('validation_cases',[]))
            results.append({'id':record['id'],'split':record['split'],'ended':prediction['ended'],
                'template':prediction['template'],'output':evidence['actual'],
                'expected_output':evidence['expected'],'error':evidence['error'],'stage':evidence['stage'],
                'render_passed':prediction['ended'] and evidence['status'] in ('passed','mismatch') and all(r['render_passed'] or r.get('rejection_matched',False) for r in scenario_results),
                'mapping_passed':prediction['ended'] and evidence['status']=='passed' and all(r['passed'] for r in scenario_results),
                'scenario_results':scenario_results})
        return results
    event('training.phase', job_id=job_id, stage='baseline_evaluation')
    before=evaluate();training=[r for r in rebuilt['examples'] if r['split']=='train']
    event('training.phase', job_id=job_id, stage='optimizer_updates')
    from app.transformations.training_sampling import coverage_samples
    sampler=coverage_samples(training)
    # Preserve previously trained behavior without using held-out reference rows.
    import re
    held_out={re.sub(r'\s+', '', row['example']['template']) for row in manifest['records'] if row['split']=='evaluation'}
    replay=[row for row in reference['examples'] if row['split']=='train'
            and re.sub(r'\s+', '', row['target']) not in held_out]
    if not replay:raise ValueError('No independent replay training examples remain.')
    replay_sampler=coverage_samples(replay)
    replay_updates=0
    started=time.monotonic();completed=0;loss_history=[]
    update_counts={row['id']:0 for row in training}
    for step in range(steps):
        if time.monotonic()-started>=120:break
        model.train();optimizer.zero_grad(set_to_none=True)
        is_feedback=step%4==0
        selected=next(sampler) if is_feedback else next(replay_sampler)
        loss=causal_loss(model,selected,device)
        if not torch.isfinite(loss):raise ValueError('Non-finite loss.')
        loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step();completed+=1
        if is_feedback:update_counts[selected['id']]+=1
        else:replay_updates+=1
        loss_history.append({'step':completed,'example_id':selected['id'],'source':'feedback' if is_feedback else 'parent_training_replay','loss':float(loss.detach().cpu())})
        if completed == 1 or completed % 50 == 0:
            event('training.progress', job_id=job_id, steps=completed)
    training_seconds=time.monotonic()-started
    event('training.phase', job_id=job_id, stage='candidate_evaluation', steps=completed)
    after=evaluate()
    from uuid import uuid4
    run=ROOT/'model-runs'/f'feedback-job-{job_id}-{uuid4().hex[:12]}'
    run.mkdir(exist_ok=False)
    candidate={**saved,'model':{k:v.detach().cpu() for k,v in model.state_dict().items()},
        'optimizer':optimizer.state_dict(),'steps':saved['steps']+completed,'feedback_bundle_sha256':bundle['content_sha256']}
    torch.save(candidate,run/'candidate-checkpoint.pt')
    report={'schema_version':2,'job_id':job_id,'bundle_sha256':bundle['content_sha256'],'prompt_contract':prompt_contract or 'legacy',
        'steps':completed,'requested_steps':steps,'update_counts':update_counts,
        'training_dynamics':{'sampler':'feedback-replay-v2','learning_rate':.00001,'replay_updates':replay_updates,'replay_examples':len(replay),'seed':23,'loss_history':loss_history,
            'training_seconds':training_seconds,'stopped_by':'step_limit' if completed==steps else 'time_limit'},
        'before':before,'after':after,'parent':parent,
        'promoted':False,'limitations':['Only this small reviewed dataset evaluated; full retention suite required.',
        'No validation-based checkpoint selection in this bounded pilot worker.','Private user feedback; no global activation.']}
    for name,data in [('feedback-bundle.json',bundle),('feedback-dataset.json',manifest),('report.json',report)]:
        (run/name).write_text(json.dumps(data,indent=2),encoding='utf-8')
    event('training.phase', job_id=job_id, stage='candidate_saved', steps=completed, outcome='not_activated')
    return {'artifact_directory':run.name,'steps':completed,'promoted':False,
        'report_sha256':hashlib.sha256((run/'report.json').read_bytes()).hexdigest(),
        'checkpoint_sha256':hashlib.sha256((run/'candidate-checkpoint.pt').read_bytes()).hexdigest(),
        'evaluation_tested':sum(r['split']=='evaluation' for r in after),
        'evaluation_render_before':sum(r['render_passed'] for r in before if r['split']=='evaluation'),
        'evaluation_render_after':sum(r['render_passed'] for r in after if r['split']=='evaluation'),
        'evaluation_before':sum(r['mapping_passed'] for r in before if r['split']=='evaluation'),
        'evaluation_after':sum(r['mapping_passed'] for r in after if r['split']=='evaluation'),
        'release_status':'requires_full_evaluation'}


@_log_traced('scripts.run_feedback_job.run_job', level=20)
def run_job(db,job_id):
    from app.transformations.worker_recovery import ownership
    interrupted=False
    job=db.get(TransformationTrainingJob,job_id)
    if job is None or job.status!='queued':raise ValueError('Job must exist and be queued.')
    try:
        claimed=db.execute(update(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id,
            TransformationTrainingJob.status=='queued').values(status='running',running_slot=1,result={'worker':ownership()}),execution_options={'synchronize_session':False})
        if claimed.rowcount!=1:db.rollback();raise ValueError('Job already claimed.')
        db.commit()
    except IntegrityError:
        _log_exception('scripts.run_feedback_job:132', handled=True)
        db.rollback();raise ValueError('Another feedback worker holds the training slot.')
    try:
        user=db.get(UserModel,job.user_id)
        if user is None or not user.is_active:raise ValueError('Owner no longer active.')
        operator(user)
        data=download(job.bundle_id,user,db)['data'];bundle=data['bundle']
        if digest({k:v for k,v in bundle.items() if k!='content_sha256'})!=job.settings['bundle_sha256']:
            raise ValueError('Bundle checksum mismatch.')
        manifest=authorized_manifest(data['dataset_id'],user,db)
        result=bounded_train(bundle,manifest,job.settings['steps'],job.id)
        db.expire_all();operator(user);authorized_manifest(data['dataset_id'],user,db)
        state='completed'
    except CleanupUncertain:
        _log_exception('scripts.run_feedback_job:145', handled=True)
        db.rollback()
        db.execute(update(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id).values(
            status='cleanup_required',result={'error':'Verify worker termination before releasing the training slot.'}))
        db.commit()
        return {'id':job_id,'status':'cleanup_required'}
    except (Exception,KeyboardInterrupt) as exc:
        _log_exception('scripts.run_feedback_job:151', handled=True)
        interrupted=isinstance(exc,KeyboardInterrupt)
        db.rollback();state='failed';result={'error':'Training or authorization checks failed. Active model unchanged.'}
    db.execute(update(TransformationTrainingJob).where(TransformationTrainingJob.id==job_id).values(status=state,running_slot=None,result=result))
    db.commit()
    if interrupted:raise KeyboardInterrupt
    return {'id':job_id,'status':state,'result':result}


@_log_traced('scripts.run_feedback_job.main', level=20)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job-id',type=int,required=True)
    args=parser.parse_args()
    from app.database.session import SessionLocal
    with SessionLocal() as db:print(json.dumps(run_job(db,args.job_id)),flush=True)


if __name__=='__main__':main()
