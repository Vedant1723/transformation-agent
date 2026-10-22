"""Small deterministic probe set, not proof of semantic correctness or anonymization."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy
from lxml import etree
from app.transformations.workbench import normalize, xml_root


@_log_traced('app.transformations.scenarios.scenarios', level=10)
def scenarios(context):
    base=copy.deepcopy(context)
    cases=[{'name':'Provided sample','context':base,'expectation':'Review output against your intended result.'}]
    fmt=base['source']['format'].upper()
    if fmt=='XML':
        root=xml_root(base['source']['payload'])
        scalar=next((n for n in root.iter() if isinstance(n.tag,str) and len(n)==0),None)
        if scalar is not None:
            scalar.text='Demo & "edge" <value>'
            c=copy.deepcopy(base);c['source']['payload']=etree.tostring(root,encoding='unicode')
            cases.append({'name':'Special-character probe','context':c,'expectation':'Observe escaping or explicit validation rejection.'})
        root=xml_root(base['source']['payload'])
        scalar=next((n for n in root.iter() if isinstance(n.tag,str) and len(n)==0 and n.getparent() is not None),None)
        if scalar is not None:
            scalar.getparent().remove(scalar)
            c=copy.deepcopy(base);c['source']['payload']=etree.tostring(root,encoding='unicode')
            cases.append({'name':'Missing XML element','context':c,'expectation':'Review whether rejection or fallback matches the requirement.'})
        root=xml_root(base['source']['payload'])
        for parent in root.iter():
            tags=[n.tag for n in parent if isinstance(n.tag,str)]
            repeated=next((tag for tag in tags if tags.count(tag)>1),None)
            if repeated:
                for child in list(parent):
                    if child.tag==repeated:parent.remove(child)
                c=copy.deepcopy(base);c['source']['payload']=etree.tostring(root,encoding='unicode')
                cases.append({'name':'Empty XML collection','context':c,'expectation':'Review whether the empty group is omitted or emitted as required.'})
                break
    else:
        payload=normalize(base['source']['payload'],fmt)
        def mutate(value,mode):
            if isinstance(value,dict):
                return {k:mutate(v,mode) for k,v in value.items()}
            if isinstance(value,list):
                return [] if mode=='empty' else [mutate(v,mode) for v in value]
            if mode=='dummy':
                if isinstance(value,bool):return not value
                if isinstance(value,(int,float)):return value+1
                if isinstance(value,str):return 'DEMO_TEST' if fmt=='ISO' else 'Demo & "edge" <value>'
            return value
        for mode,label in [('dummy','Generated dummy values'),('empty','Empty collections')]:
            altered=mutate(payload,mode)
            if altered!=payload:
                c=copy.deepcopy(base);c['source']['payload']=altered
                cases.append({'name':label,'context':c,'expectation':'Observed behavior only: inspect business rules, output and validation errors.'})
        if payload:
            altered=copy.deepcopy(payload);del altered[next(iter(altered))]
            c=copy.deepcopy(base);c['source']['payload']=altered
            cases.append({'name':'Missing input field','context':c,'expectation':'A required-field rejection may be correct; absence of an error is not proof of correctness.'})
    return cases[:4]
