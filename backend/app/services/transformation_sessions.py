from app.core.observability import traced as _log_traced, exception_event as _log_exception
from app.schemas.correction import CorrectionCase
"""Phase-one conversation state. Explicit deterministic actions, no trained model claims."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.models.user import UserModel
from app.transformations.conversation_models import TransformationSession
from app.schemas.transformations import TransformationChatRequest, TransformationTestRequest
from app.transformations.workbench import generate, parse_instructions
from app.services.transformations import test_template
from app.transformations.scenarios import scenarios
from app.transformations.chat_intake import parse_pasted_message, MissingDirection, MissingPayload
from app.transformations.conversation_language import normalize_conversation_command, direction_reply
from app.transformations.collection_filters import parse_filter_batch,filter_key,describe_filter,remove_filter
from app.transformations.conversation_summary import SUMMARY_COMMANDS,requirements_summary



class NewSession(BaseModel):
    title: str = Field(default='Untitled transformation',min_length=1,max_length=200)


class Turn(BaseModel):
    version: int = Field(ge=0)
    action: Literal['message','context','template','restore','review','apply_fix'] = 'message'
    message: str = Field(default='',max_length=60000)
    context: TransformationChatRequest | None = None
    template: str | None = Field(default=None,max_length=50000)
    revision: int | None = None
    review: Literal['approved','rejected','candidate'] = 'candidate'
    sanitized: bool = False
    fix_id: str | None = Field(default=None,max_length=200)




class Correction(BaseModel):
    version: int = Field(ge=0)
    revision: int = Field(ge=1)
    corrected_template: str = Field(min_length=1,max_length=50000)
    expected_output: str = Field(min_length=1,max_length=50000)
    feedback: str = Field(default='',max_length=2000)
    validation_cases: list[CorrectionCase] = Field(default_factory=list,max_length=8)


@_log_traced('app.services.transformation_sessions.submit_correction', level=20)
def submit_correction(session_id:int,request:Correction,user:UserModel,db:Session):
    """Validate a private candidate; never auto-approve or train user feedback."""
    from app.transformations.scoring import score_case,canonical
    row=owned(db,user,session_id)
    if row.version!=request.version:raise HTTPException(409,'Conversation changed. Reload before submitting.')
    state=copy.deepcopy(row.state)
    original=next((r for r in state['revisions'] if r['id']==request.revision),None)
    if original is None:raise HTTPException(404,'Template revision not found.')
    if len(state['revisions'])>=100:raise HTTPException(422,'Conversation revision limit reached.')
    context=copy.deepcopy(original['context'])
    from app.transformations.correction_cases import validate_cases,replay_cases
    cases=[case.model_dump(exclude_none=True) for case in request.validation_cases]
    try:validate_cases(cases,context['target']['format'])
    except Exception as exc:_log_exception('app.services.transformation_sessions:66', handled=True); raise HTTPException(422,'Invalid scenario output or scenario size limit exceeded.') from exc
    try:canonical(request.expected_output,context['target']['format'])
    except Exception as exc:_log_exception('app.services.transformation_sessions:68', handled=True); raise HTTPException(422,'Expected output is invalid for the target format.') from exc
    record={'id':'submitted-correction','example':{'context':context,'template':request.corrected_template,'test':{'output':request.expected_output}}}
    execution=score_case(record,'replay')
    if execution['status']=='infrastructure_error':raise HTTPException(503,'Renderer unavailable. Correction was not saved; retry later.')
    try:case_results=replay_cases(context,request.corrected_template,cases)
    except ConnectionError as exc:_log_exception('app.services.transformation_sessions:73', handled=True); raise HTTPException(503,'Renderer unavailable. Correction was not saved; retry later.') from exc
    append_revision(state,request.corrected_template,context,f'User correction of revision {request.revision}')
    revision=current(state)
    passed=execution['status']=='passed' and all(case['passed'] for case in case_results)
    revision['test']={'passed':passed,'render_passed':execution['status'] in ('passed','mismatch'),
                      'mapping_passed':passed,'output':execution['actual'],'expected_output':request.expected_output,
                      'error':execution['error'],'stage':execution['stage']}
    revision['test_context']=context
    correction={'revision':revision['id'],'parent_revision':request.revision,
                'status':'needs_review' if passed else 'validation_failed','learned':False,'sharing':'private',
                'feedback':request.feedback,'created_at':datetime.now(timezone.utc).isoformat(),
                'test':copy.deepcopy(revision['test']), 'validation_cases':cases,'case_results':case_results}
    revision['correction']=correction
    state['examples'].append({'schema_version':1,'revision':revision['id'],'status':'candidate',
        'sanitized_attested':False,'feedback':request.feedback,'context':context,'template':request.corrected_template,
        'test':copy.deepcopy(revision['test']),'validation_cases':cases,'case_results':case_results,
        'conversation':[], 'created_at':correction['created_at']})
    if len(json.dumps(state).encode())>4_000_000:raise HTTPException(422,'Conversation exceeds storage limit.')
    changed=db.execute(update(TransformationSession).where(TransformationSession.id==row.id,
        TransformationSession.user_id==user.id,TransformationSession.version==request.version).values(
        state=state,version=request.version+1,updated_at=datetime.now(timezone.utc)),execution_options={'synchronize_session':False})
    if changed.rowcount!=1:
        db.rollback();raise HTTPException(409,'Conversation changed. Reload before submitting.')
    db.commit()
    return {'success':True,'data':{**correction,'session_id':session_id,'version':request.version+1,'test':revision['test']}}


@_log_traced('app.services.transformation_sessions.read_correction', level=20)
def read_correction(session_id:int,revision_id:int,user:UserModel,db:Session):
    row=owned(db,user,session_id)
    revision=next((r for r in row.state['revisions'] if r['id']==revision_id and r.get('correction')),None)
    if revision is None:raise HTTPException(404,'Correction not found.')
    from app.services.transformation_datasets import list_candidates
    candidate=next((item for item in list_candidates(user,db)['data'] if item['session_id']==session_id and item['revision']==revision_id),None)
    from app.transformations.correction_lineage import correction_lineage
    learning=correction_lineage(db,user.id,session_id,revision_id,candidate.get('fingerprint') if candidate else None)
    return {'success':True,'data':{**revision['correction'],'session_id':session_id,'version':row.version,
        'review_status':candidate['status'] if candidate else 'candidate',
        'dataset_eligible':bool(candidate and candidate['eligible']),
        'eligibility_reasons':candidate['reasons'] if candidate else ['No reviewed example'],
        'training_status':learning['status'],'learning_history':learning,'active_model_learning_confirmed':False}}


class CorrectionReview(BaseModel):
    version: int = Field(ge=0)
    decision: Literal['approved','rejected']
    sanitized: bool = False
    feedback: str = Field(default='',max_length=2000)


@_log_traced('app.services.transformation_sessions.review_correction', level=20)
def review_correction(session_id:int,revision_id:int,request:CorrectionReview,user:UserModel,db:Session):
    row=owned(db,user,session_id)
    revision=next((r for r in row.state['revisions'] if r['id']==revision_id and r.get('correction')),None)
    if revision is None:raise HTTPException(404,'Correction not found.')
    if row.state['current']!=revision_id:raise HTTPException(409,'Only the current correction can be reviewed. Reload the conversation.')
    turn(session_id,Turn(version=request.version,action='review',review=request.decision,
        sanitized=request.sanitized,message=request.feedback),user,db)
    return read_correction(session_id,revision_id,user,db)


@_log_traced('app.services.transformation_sessions.owned', level=20)
def owned(db,user,session_id):
    row=db.scalar(select(TransformationSession).where(TransformationSession.id==session_id,TransformationSession.user_id==user.id))
    if row is None:
        raise HTTPException(404,'Transformation conversation not found.')
    return row


@_log_traced('app.services.transformation_sessions.view', level=20)
def view(row):
    return {'id':row.id,'title':row.title,'version':row.version,'state':row.state}


@_log_traced('app.services.transformation_sessions.sessions', level=20)
def sessions(user:UserModel,db:Session):
    rows=db.scalars(select(TransformationSession).where(TransformationSession.user_id==user.id).order_by(TransformationSession.updated_at.desc()).limit(100)).all()
    return {'success':True,'data':[{'id':r.id,'title':r.title,'version':r.version} for r in rows]}


@_log_traced('app.services.transformation_sessions.create', level=20)
def create(request:NewSession,user:UserModel,db:Session):
    row=TransformationSession(user_id=user.id,title=request.title,version=0,state={
        'messages':[{'role':'assistant','text':'Add your source and target examples, then ask me to generate. Phase 1 uses explicit commands; your own trained model comes in a later phase.'}],
        'context':None,'revisions':[],'current':None,'examples':[]})
    db.add(row);db.commit();db.refresh(row)
    return {'success':True,'data':view(row)}


@_log_traced('app.services.transformation_sessions.read', level=20)
def read(session_id:int,user:UserModel,db:Session):
    return {'success':True,'data':view(owned(db,user,session_id))}


@_log_traced('app.services.transformation_sessions.current', level=20)
def current(state):
    return next((r for r in state['revisions'] if r['id']==state['current']),None)


@_log_traced('app.services.transformation_sessions.append_revision', level=20)
def append_revision(state,template,config,reason,mappings=None):
    revision={'id':len(state['revisions'])+1,'template':template,'context':copy.deepcopy(config),
        'reason':reason,'mappings':mappings or [],'test':None,
        'hash':hashlib.sha256(template.encode()).hexdigest()}
    state['revisions'].append(revision)
    state['current']=revision['id']


@_log_traced('app.services.transformation_sessions.execute_version', level=20)
def execute_version(revision,context,user,db):
    return test_template(TransformationTestRequest(template=revision['template'],input_payload=context['source']['payload'],
        source_format=context['source']['format'],target_format=context['target']['format'],direction=context['direction'],
        additionalProperties=context.get('additionalProperties',{}),headers=context.get('headers',{})),user,db)['data']


@_log_traced('app.services.transformation_sessions.run_scenarios', level=20)
def run_scenarios(revision,context,user,db):
    results=[]
    for case in scenarios(context):
        result=execute_version(revision,case['context'],user,db)
        results.append({**case,'result':result})
    revision['scenarios']=results
    revision['test']=results[0]['result']
    revision['test_context']=copy.deepcopy(context)
    return f"Executed {len(results)} scenarios; {sum(c['result']['passed'] for c in results)} rendered valid output. Rejections may be expected. These are probes, not a production-readiness verdict."


@_log_traced('app.services.transformation_sessions.turn', level=20)
def turn(session_id:int,request:Turn,user:UserModel,db:Session):
    row=owned(db,user,session_id)
    if row.version!=request.version:
        raise HTTPException(409,'This conversation changed elsewhere. Reload before continuing.')
    state=copy.deepcopy(row.state)
    if request.action=='message' and request.context is not None and request.message.lower().strip().rstrip('.!') not in SUMMARY_COMMANDS:
        state['context']=request.context.model_dump()
    if len(state['messages'])>=200 or len(state['revisions'])>=100:
        raise HTTPException(422,'This demo conversation is full. Start a new conversation; existing work remains saved.')
    text=request.message.strip()
    original_text=text
    text=normalize_conversation_command(text)
    pasted=None
    clarification=None
    summarizing=request.action=='message' and text.lower().strip().rstrip('.!') in SUMMARY_COMMANDS
    if request.action=='message' and not summarizing:
        pending=state.pop('pending_direction_message',None)
        pending_payload=state.pop('pending_payload_message',None)
        parse_text=(pending+'\n'+direction_reply(text)) if pending and direction_reply(text) else text
        if pending_payload and ('```' in text) and not re.match(r'^\s*(?:please\s+)?(?:generate|make|create|fix)\b',text,re.I):
            parse_text=pending_payload+'\n'+text
        try:
            pasted=parse_pasted_message(parse_text,state.get('context'))
        except MissingPayload as exc:
            _log_exception('app.services.transformation_sessions:212', handled=True)
            clarification=str(exc)
            state=copy.deepcopy(row.state)
            state.pop('pending_direction_message',None)
            state['pending_payload_message']=parse_text
        except MissingDirection as exc:
            _log_exception('app.services.transformation_sessions:217', handled=True)
            clarification=str(exc)
            state=copy.deepcopy(row.state)
            state.pop('pending_payload_message',None)
            state['pending_direction_message']=parse_text
        except ValueError as exc:
            _log_exception('app.services.transformation_sessions:222', handled=True)
            clarification=str(exc)
            state=copy.deepcopy(row.state)
            state.pop('pending_direction_message',None)
            state.pop('pending_payload_message',None)
        if pasted:
            state['context']=pasted['context']
            text=pasted['command']
            if pasted['template']:
                append_revision(state,pasted['template'],state['context'],'Pasted template from chat; original preserved')
    reply=''
    if clarification:
        reply='I need clarification before changing anything. '+clarification+' Your current template and inputs are unchanged. Edit and resend the full message with the missing details.'
        if state.get('pending_direction_message'):
            reply='Is this a request or response transformation? Reply “request” or “response” and I’ll use the payloads you just pasted. Nothing has been generated yet.'
        elif state.get('pending_payload_message'):
            reply=clarification+' Send only the missing labelled block, or start a new complete generation message. Your current template remains unchanged.'
        state['clarification']=reply
    elif request.action=='context':
        if request.context is None:
            raise HTTPException(422,'Supply source and target context.')
        state['context']=request.context.model_dump()
        reply='Context saved. Existing versions are unchanged. Say “generate” to create a version using these inputs.'
    elif request.action=='restore':
        revision=next((r for r in state['revisions'] if r['id']==request.revision),None)
        if revision is None:
            raise HTTPException(422,'Choose an existing version.')
        state['context']=copy.deepcopy(revision['context'])
        append_revision(state,revision['template'],revision['context'],f'Restored version {revision["id"]}',revision['mappings'])
        reply='Restored as a new version. Earlier versions remain available. Test this version before approving it.'
    elif request.action=='template':
        if not request.template or not state['context']:
            raise HTTPException(422,'Save context and supply a nonempty template first.')
        append_revision(state,request.template,state['context'],text or 'Manual template edit')
        reply='Template saved as a new version. Say “test” to execute it.'
    elif request.action=='apply_fix':
        revision=current(state)
        if not revision or not revision.get('test'):
            raise HTTPException(422,'Test the current version before choosing a fix.')
        context=state['context'] or revision['context']
        if context!=revision.get('test_context'):
            raise HTTPException(409,'Inputs changed since the test. Test again before applying a fix.')
        suggestion=next((s for s in revision['test'].get('suggestions',[]) if s['id']==request.fix_id),None)
        if not suggestion:
            raise HTTPException(422,'Choose a suggestion from the current test results.')
        start,end=suggestion['start'],suggestion['end']
        if not 0<=start<=end<=len(revision['template']) or revision['template'][start:end]!=suggestion['before']:
            raise HTTPException(409,'Suggestion no longer matches the template. Test again.')
        template=revision['template'][:start]+suggestion['after']+revision['template'][end:]
        append_revision(state,template,context,'User-approved fix: '+suggestion['title'],revision['mappings'])
        saved=current(state)
        saved['test']=execute_version(saved,context,user,db)
        saved['test_context']=copy.deepcopy(context)
        reply='Applied your selected fix as a new version and executed it. '+('Output syntax passed; inspect the output before approval.' if saved['test']['passed'] else 'The new test still fails; inspect its error and remaining suggestions.')
    elif request.action=='review':
        revision=current(state)
        if not revision:
            raise HTTPException(422,'Create a template version first.')
        if request.review=='approved' and revision.get('correction'):
            from app.transformations.scoring import score_case
            if not request.sanitized:raise HTTPException(422,'Approval requires sanitization confirmation.')
            context=revision['context']
            expected=revision['correction']['test']['expected_output']
            evidence=score_case({'id':'correction-review','example':{'context':context,
                'template':revision['template'],'test':{'output':expected}}},'replay')
            if evidence['status']=='infrastructure_error':raise HTTPException(503,'Renderer unavailable. Review was not saved.')
            if evidence['status']!='passed':raise HTTPException(422,'Correction must match its submitted expected output before approval.')
            from app.transformations.correction_cases import replay_cases
            try:case_results=replay_cases(context,revision['template'],revision['correction'].get('validation_cases',[]))
            except ConnectionError as exc:_log_exception('app.services.transformation_sessions:291', handled=True); raise HTTPException(503,'Renderer unavailable. Review was not saved.') from exc
            if not all(case['passed'] for case in case_results):
                raise HTTPException(422,'Correction must pass every submitted scenario before approval.')
            revision['correction']['case_results']=case_results
            revision['test']={'passed':True,'render_passed':True,'mapping_passed':True,
                'output':evidence['actual'],'expected_output':expected,'error':'','stage':evidence['stage']}
            revision['test_context']=copy.deepcopy(context)
        if request.review=='approved' and (not request.sanitized or not revision.get('test',{} ) or not revision['test'].get('passed')):
            raise HTTPException(422,'Approval requires a passing test and confirmation that the example contains no sensitive data.')
        state['examples'].append({'schema_version':1,'revision':revision['id'],'status':request.review,
            'sanitized_attested':request.sanitized,'feedback':text,'context':copy.deepcopy(revision.get('test_context') or revision['context']),
            'template':revision['template'],'test':copy.deepcopy(revision['test']),
            'validation_cases':copy.deepcopy(revision.get('correction',{}).get('validation_cases',[])),
            'case_results':copy.deepcopy(revision.get('correction',{}).get('case_results',[])),
            'scenarios':copy.deepcopy(revision.get('scenarios',[])),
            'conversation':copy.deepcopy(state['messages']),'created_at':datetime.now(timezone.utc).isoformat()})
        reply='Review saved as a dataset example. It does not train a model or change future predictions yet.'
    else:
        if not text:
            raise HTTPException(422,'Enter a message.')
        command=text.lower().strip().rstrip('.!')
        revision=current(state)
        if summarizing:
            reply=requirements_summary(state)
        elif command in ('test scenarios','test all scenarios','generate test data','test different scenarios'):
            if not revision:
                reply='Generate or paste a template first, then ask “test scenarios”.'
            else:
                reply=run_scenarios(revision,state['context'] or revision['context'],user,db)
        elif command in ('fix','fix it','fix the transformation','fix transformation'):
            if not revision:
                reply='Paste or generate the transformation first so I can execute it and inspect its error.'
            else:
                c=state['context'] or revision['context']
                revision.pop('scenarios',None)
                result=execute_version(revision,c,user,db)
                revision['test']=result;revision['test_context']=copy.deepcopy(c)
                allowed={'Escape XML text','Match escaping to output format','Escape JSON string content','Use JSON number/boolean formatting'}
                edits=[s for s in result['suggestions'] if s.get('confidence')=='high' and s['title'] in allowed]
                if result['passed']:
                    reply='The supplied sample already passes, so I did not change the template. '+run_scenarios(revision,c,user,db)
                elif pasted:
                    reply='Executed the pasted template without changing it. Review the actual error and proposed changes in Results, then choose a fix to create and test a new version.'
                elif not edits:
                    reply='I ran the template and preserved its error in Results. No conservative formatting fix is available. Review the suggested mapping/type changes or clarify the intended behavior; I will not remove validations or invent defaults.'
                else:
                    proposal=revision['template'];boundary=len(proposal)
                    for edit in sorted(edits,key=lambda s:s['start'],reverse=True):
                        if edit['end']>boundary or proposal[edit['start']:edit['end']]!=edit['before']:
                            continue
                        proposal=proposal[:edit['start']]+edit['after']+proposal[edit['end']:];boundary=edit['start']
                    append_revision(state,proposal,c,'Automatic formatting repair requested in chat',revision['mappings'])
                    reply='Saved a new version with conservative formatting fixes; the original remains in Versions. '+run_scenarios(current(state),c,user,db)
        elif command in ('test','run','test it','run it','test transformation'):
            if not revision:
                reply='There is no template to test yet. Save the payload context and generate or paste a template first.'
            else:
                c=state['context'] or revision['context']
                result=execute_version(revision,c,user,db)
                revision.pop('scenarios',None)
                revision['test']=result
                revision['test_context']=copy.deepcopy(c)
                reply='Execution and output checks passed. Review the output before approving a training example.' if result['passed'] else 'The test failed. The result panel shows the actual error and available fix suggestions; your template was not changed.'
        elif not state['context']:
            reply='Please add the source payload and target example in Context. I need those before I can generate a transformation.'
        else:
            config=copy.deepcopy(state['context'])
            should_generate=command in ('generate','generate it','generate transformation','regenerate')
            filter_error=None
            try:
                remaining_filters=remove_filter(text,config.get('filters',[]))
                filter_rules=parse_filter_batch(text)
                if remaining_filters is not None:
                    config['filters']=remaining_filters
                    should_generate=True
            except ValueError as exc:
                _log_exception('app.services.transformation_sessions:366', handled=True)
                filter_rules=[]
                filter_error=str(exc)
            if filter_rules:
                keys={filter_key(r) for r in filter_rules}
                config['filters']=[r for r in config.get('filters',[]) if filter_key(r) not in keys]+filter_rules
                should_generate=True
            elif command=='clear collection filters':
                config['filters']=[]
                should_generate=True
            mapping=re.fullmatch(r'(?:please\s+)?map\s+(\S+)\s+to\s+(\S+)',text,re.I)
            if mapping:
                config.setdefault('mappings',{})[mapping[2]]=mapping[1]
                should_generate=True
            if not should_generate and not filter_error:
                try:
                    fields=generate(TransformationChatRequest(**{**config,'message':''}))['source_fields']
                    rules=parse_instructions(text,fields)
                    if rules:
                        merged={(r['field'],r['type']):r for r in config.get('validations',[])}
                        merged.update({(r['field'],r['type']):r for r in rules})
                        config['validations']=list(merged.values())
                        should_generate=True
                except (ValueError,TypeError,KeyError):
                    _log_exception('app.services.transformation_sessions:389', handled=True)
                    pass
            if should_generate:
                try:
                    config['message']=''
                    result=generate(TransformationChatRequest(**config))
                    state['context']=config
                    append_revision(state,result['template'],config,text,result['mappings'])
                    saved=current(state)
                    saved['test']=execute_version(saved,config,user,db)
                    saved['test_context']=copy.deepcopy(config)
                    reply='Generated and executed using the current sample input. '+('Output syntax passed; review the mappings and actual output.' if saved['test']['passed'] else 'Execution failed; inspect the actual error and suggested fixes in Results.')
                    if not saved['test']['passed'] and 'validation failed' in (saved['test'].get('error') or ''):
                        reply='Generated the transformation, but your supplied input was rejected by a validation rule. The template and rule are preserved. Check Results for the exact field/error; correct the input or explicitly revise the rule, then test again. A validation rejection does not by itself mean the template is broken.'
                    if result['warnings']:
                        reply+=' Mapping warnings: '+' '.join(result['warnings'][:3])
                    if config.get('filters'):
                        reply+=' Active collection filters: '+'; '.join(describe_filter(r) for r in config['filters'])+'. Missing or nonnumeric comparison fields are excluded.'
                    if pasted and pasted.get('source_preset'):
                        reply+=' Source: synthetic '+pasted['source_preset']+' preset, not your verified organisation payload. Review or replace it before real use.'
                except (ValueError,TypeError,KeyError) as exc:
                    _log_exception('app.services.transformation_sessions:409', handled=True)
                    reply='No template was changed. '+str(exc)
            else:
                reply=('No template was changed. '+filter_error) if filter_error else 'I cannot reliably interpret that request yet. Use generate, test, map SOURCE to TARGET, validation rules, or one explicit collection filter per line. Example: include only items where items[0].amount >= 100. Other business logic needs clarification; no implementation was invented.'
    if not clarification and not summarizing:
        state.pop('clarification',None)
        state.pop('pending_direction_message',None)
        state.pop('pending_payload_message',None)
    state['messages'] += [{'role':'user','text':original_text or request.action},{'role':'assistant','text':reply}]
    if len(json.dumps(state).encode())>4_000_000:
        raise HTTPException(422,'Conversation exceeds the 4 MB demo storage limit. Start a new conversation with smaller examples.')
    changed=db.execute(update(TransformationSession).where(TransformationSession.id==row.id,TransformationSession.user_id==user.id,
        TransformationSession.version==request.version).values(state=state,version=request.version+1,updated_at=datetime.now(timezone.utc)),execution_options={'synchronize_session':False})
    if changed.rowcount!=1:
        db.rollback()
        raise HTTPException(409,'This conversation changed elsewhere. Reload before continuing.')
    db.commit();db.refresh(row)
    return {'success':True,'data':view(row)}
