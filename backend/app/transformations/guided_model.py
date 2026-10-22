"""Opt-in agent-compiled candidates ranked by the existing model, not free generation."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy
import json
import math
import re


@_log_traced('app.transformations.guided_model.validate', level=10)
def validate(source,target,kind,selected=None,target_format='JSON'):
    if not isinstance(source,dict) or not 1<=len(source)<=8:raise ValueError('Guided scope: 1–8 flat JSON fields.')
    if target_format not in ('JSON','XML') or kind not in ('string','number','boolean'):raise ValueError('Unsupported guided output type.')
    for key in [target,*source]:
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',key):raise ValueError('Use simple field names: letters, digits and underscores; start with a letter or underscore.')
    for value in source.values():
        if type(value) is str:
            if len(value)>256:raise ValueError('Guided strings are limited to 256 characters.')
        elif type(value) in (int,float):
            if abs(value)>1e9 or not math.isfinite(value):raise ValueError('Guided numbers must be finite and within ±1 billion.')
        elif type(value) is not bool:raise ValueError('Guided scope excludes nulls, objects and lists.')
    keys=[key for key,value in source.items() if (kind=='string' and type(value)is str) or (kind=='number' and type(value) in (int,float)) or (kind=='boolean' and type(value)is bool)]
    if selected is not None and selected not in keys:raise ValueError('Selected source must exist and match the output type.')
    if not keys:raise ValueError('No source fields match the requested output type.')
    return [selected] if selected else keys


@_log_traced('app.transformations.guided_model.candidates', level=10)
def candidates(source,target,kind,selected,target_format):
    from app.schemas.transformations import TransformationChatRequest
    from app.transformations.workbench import generate
    from xml.sax.saxutils import escape
    from decimal import Decimal
    keys=validate(source,target,kind,selected,target_format)
    shape={'string':'','number':0,'boolean':False}[kind]
    context={'direction':'REQUEST','source':{'format':'JSON','payload':source},
        'target':{'format':target_format,'payload':{target:shape} if target_format=='JSON' else f'<Payment><{target}/></Payment>'},
        'mappings':{},'validations':[]}
    rows=[]
    for key in keys:
        mapped=copy.deepcopy(context);mapped['mappings']={target if target_format=='JSON' else f'Payment.{target}':key}
        template=generate(TransformationChatRequest(**mapped))['template']
        value=source[key]
        text='true' if value is True else 'false' if value is False else str(value)
        if kind=='number':
            text=format(Decimal(str(value)),'f')
            if '.' in text:text=text.rstrip('0').rstrip('.')
            if value==0:text='0'
        json_value=int(value) if type(value)is float and value.is_integer() else value
        expected=json.dumps({target:json_value}) if target_format=='JSON' else f'<Payment><{target}>{escape(text)}</{target}></Payment>'
        rows.append({'source_field':key,'template':template,'expected':expected})
    if selected:context['mappings']=mapped['mappings']
    return context,rows


@_log_traced('app.transformations.guided_model.score_candidate', level=10)
def score_candidate(record,kind):
    from app.transformations.scoring import score_case,canonical
    from decimal import Decimal,InvalidOperation
    from lxml import etree
    result=score_case(record,'replay')
    # XML numeric fields have a declared numeric value, not an exact lexical format.
    if kind=='number' and record['example']['context']['target']['format']=='XML' and result['status']=='mismatch':
        try:
            actual=etree.fromstring(canonical(result['actual'],'XML'))
            expected=etree.fromstring(canonical(result['expected'],'XML'))
            if len(actual)==len(expected)==1 and len(actual[0])==len(expected[0])==0:
                left=Decimal(actual[0].text or '');right=Decimal(expected[0].text or '')
                if left.is_finite() and right.is_finite() and left==right:
                    actual[0].text=expected[0].text
                    if canonical(etree.tostring(actual).decode(),'XML')==canonical(result['expected'],'XML'):result['status']='passed'
        except (ValueError,InvalidOperation,etree.XMLSyntaxError):_log_exception('app.transformations.guided_model:67', handled=True); pass
    return result


@_log_traced('app.transformations.guided_model.run', level=10)
def run(model,tokenizer,source,target,kind,selected,target_format):
    import torch
    from app.transformations.training_bundle import BOS,SEP,EOS,encode,pair
    from app.transformations.tiny_model import generate_template
    from app.transformations.scoring import score_case
    context,rows=candidates(source,target,kind,selected,target_format)
    record={'id':'guided-preview','split':'evaluation','provenance':{},'example':{'context':context,'template':'','test':{'output':''}}}
    prompt=pair(record)['prompt'];prefix=[BOS]+encode(prompt,tokenizer)+[SEP]
    model.eval()
    with torch.inference_mode():
        for row in rows:
            tokens=encode(row['template'],tokenizer)+[EOS]
            if len(prefix)+len(tokens)>model.config['context_length']:raise ValueError('Guided prompt and candidate exceed model context; simplify the source.')
            ids=torch.tensor([prefix+tokens[:-1]])
            logits=model(ids)[0,len(prefix)-1:]
            loss=torch.nn.functional.cross_entropy(logits,torch.tensor(tokens))
            if not torch.isfinite(loss):raise ValueError('Non-finite candidate score.')
            row['mean_token_loss']=float(loss)
    rows.sort(key=lambda row:(row['mean_token_loss'],row['source_field']))
    chosen=rows[0]
    record['example']['template']=chosen['template'];record['example']['test']['output']=chosen['expected']
    execution=score_candidate(record,kind)
    raw=generate_template(model,prompt,tokenizer,'cpu',max_new_tokens=850)
    record['example']['template']=raw['template'];raw_execution=score_case(record,'replay')
    if any(r['status']=='infrastructure_error' for r in (execution,raw_execution)):raise RuntimeError('FreeMarker service unavailable.')
    rendered=execution['status'] in ('passed','mismatch')
    confirmed=selected is not None and execution['status']=='passed'
    return {'engine':'agent-compiled/model-ranked','passed':confirmed,'render_passed':rendered,
        'mapping_passed':confirmed,'mapping_confirmed_by_user':selected is not None,
        'selected_source':chosen['source_field'],'template':chosen['template'],'output':execution['actual'],
        'expected_for_selected_mapping':chosen['expected'],'error':execution['error'],
        'ranking':[{'source_field':r['source_field'],'mean_token_loss':r['mean_token_loss']} for r in rows],
        'raw_model':{'template':raw['template'],'output':raw_execution['actual'],'error':raw_execution['error'],
            'ended':raw['ended'],'render_passed':raw['ended'] and raw_execution['status'] in ('passed','mismatch')},
        'approved':False,'fallback_used':False,'weights_changed':False,
        'warning':'The agent compiles candidate FreeMarker; the existing model ranks it. This is not unrestricted model generation. Scores are not confidence probabilities. Confirm the source mapping and review before use.'}
