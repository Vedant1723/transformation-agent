"""Read verified candidate evidence. Never deserialize or activate a checkpoint."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import hashlib
import json
import re
import math


@_log_traced('app.transformations.candidate_report.read_candidate_report', level=10)
def read_candidate_report(root,job,bundle):
    directory=job.result.get('artifact_directory','')
    if not re.fullmatch(rf'feedback-job-{job.id}-[0-9a-f]{{12}}',directory):
        raise ValueError('Invalid candidate artifact reference.')
    base=(root/'model-runs').resolve()
    folder=base/directory
    if folder.resolve()!=folder or not folder.is_dir():
        raise ValueError('Candidate directory is missing or redirected.')
    def verified(name,key,limit,read=False):
        path=folder/name
        expected=job.result.get(key,'')
        if not re.fullmatch(r'[0-9a-f]{64}',expected):raise ValueError('Legacy job has no verified report; run a new candidate job.')
        if path.resolve()!=path or not path.is_file() or path.stat().st_size>limit:
            raise ValueError('Candidate artifact is missing, redirected or oversized.')
        digest=hashlib.sha256();chunks=[]
        with path.open('rb') as source:
            total=0
            while chunk:=source.read(1024*1024):
                total+=len(chunk)
                if total>limit:raise ValueError('Candidate artifact exceeds limit.')
                digest.update(chunk)
                if read:chunks.append(chunk)
        if digest.hexdigest()!=expected:raise ValueError('Candidate artifact checksum mismatch.')
        return b''.join(chunks)
    raw=verified('report.json','report_sha256',8_000_000,True)
    verified('candidate-checkpoint.pt','checkpoint_sha256',100_000_000)
    report=json.loads(raw)
    if (report.get('schema_version')!=2 or report.get('job_id')!=job.id or
        report.get('bundle_sha256')!=job.settings['bundle_sha256'] or report.get('promoted') is not False):
        raise ValueError('Report does not match this candidate job.')
    steps=report.get('steps')
    if type(steps) is not int or not 0<steps<=job.settings['steps'] or steps!=job.result.get('steps'):
        raise ValueError('Training-step evidence is inconsistent.')
    expected={row['id']:row['split'] for row in bundle['examples']}
    updates=report.get('update_counts',{})
    if not isinstance(updates,dict) or set(updates)!={k for k,v in expected.items() if v=='train'}:
        raise ValueError('Training sample evidence is inconsistent.')
    if any(type(n) is not int or n<0 for n in updates.values()) or sum(updates.values())!=steps:
        raise ValueError('Training sample counts do not match optimizer steps.')
    dynamics=report.get('training_dynamics')
    if dynamics is not None:
        history=dynamics.get('loss_history',[])
        if len(history)!=steps:raise ValueError('Training loss history is incomplete.')
        counted={key:0 for key in updates}
        for index,event in enumerate(history,1):
            value=event.get('loss')
            if event.get('step')!=index or event.get('example_id') not in counted or type(value) not in (float,int) or not math.isfinite(value) or value<0:
                raise ValueError('Training loss history is invalid.')
            counted[event['example_id']]+=1
        if counted!=updates:raise ValueError('Training history disagrees with sampling counts.')
    indexed={}
    for phase in ('before','after'):
        rows=report.get(phase,[])
        if not isinstance(rows,list) or len(rows)!=len(expected):raise ValueError('Evaluation examples are incomplete.')
        indexed[phase]={row['id']:row for row in rows}
        if {row['id']:row['split'] for row in rows}!=expected:raise ValueError('Evaluation split evidence is inconsistent.')
        for row in rows:
            if any(type(row.get(key)) is not bool for key in ('ended','render_passed','mapping_passed')):
                raise ValueError('Evaluation verdict is invalid.')
    comparisons=[]
    for identifier,split in expected.items():
        before=indexed['before'][identifier];after=indexed['after'][identifier]
        change='improved' if not before['mapping_passed'] and after['mapping_passed'] else 'regressed' if before['mapping_passed'] and not after['mapping_passed'] else 'unchanged'
        comparisons.append({'id':identifier,'split':split,'optimizer_updates':updates.get(identifier,0),
            'change':change,'before':before,'after':after})
    return {'job_id':job.id,'integrity_verified':True,'active_model_changed':False,
        'steps':steps,'requested_steps':job.settings['steps'],'examples':comparisons,
        'training_dynamics':dynamics,
        'training_coverage':{'seen':sum(n>0 for n in updates.values()),'total':len(updates),
            'complete_passes':min(updates.values(),default=0)},
        'checkpoint_sha256':job.result['checkpoint_sha256'],'report_sha256':job.result['report_sha256'],
        'limitations':report.get('limitations',[]),'ready_to_activate':False}
