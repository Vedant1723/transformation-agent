"""Bounded static sample inference; never claims a sample satisfies business rules."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy
import re
from lxml import etree
from app.transformations.template_tools import REFERENCE


@_log_traced('app.transformations.payload_generator.generate_payload', level=10)
def generate_payload(template, source_format='JSON', direction='REQUEST', xml_root='root'):
    clean=re.sub(r'<#--[\s\S]*?-->','',template)
    warnings=['Synthetic input inferred from static references. Review values and run Test; validation rules and dynamic expressions may require edits.']
    aliases={}
    for match in re.finditer(r'<#list\s+\(?((?:body|[A-Za-z_]\w*)[.\[][^\s)>!]*)(?:\))?(?:!\[\])?\s+as\s+(\w+)\s*>',clean):
        path=match[1]
        for alias,reference in aliases.items():
            if path.startswith(alias+'.'):path=reference+path[len(alias):]
        if match[2] in aliases and aliases[match[2]]!=path+'[0]':
            raise ValueError('Loop alias is reused with different sources; supply a representative payload manually.')
        aliases[match[2]]=path+'[0]'
    expanded=clean
    for alias,path in aliases.items():
        expanded=re.sub(r'\b'+re.escape(alias)+r'(?=[.\[])',lambda _:path,expanded)
    refs=sorted(set(REFERENCE.findall(expanded)) | {p for p in aliases.values() if p.startswith(('body.','body['))})
    paths=[]
    for reference in refs:
        if not reference.startswith(('body.','body[')):continue
        parts=[]
        for token in re.finditer(r'\.([A-Za-z_]\w*)|\[(\d+)|\["([^"\n]*)"\]|\[\x27([^\x27\n]*)\x27\]',reference[4:]):
            parts.append(int(token[2]) if token[2] else token[1] or token[3] or token[4])
        if parts:paths.append((parts,reference))
    # Initializer/parent guards aren't leaf requirements when descendants exist.
    paths=[(p,r) for p,r in paths if not any(len(q)>len(p) and q[:len(p)]==p for q,_ in paths)]
    if len(paths)>200:raise ValueError('Too many inferred fields; maximum 200.')
    data={};props={};headers={}
    def put(node,path,value):
        key=path[0]
        if isinstance(key,int):
            if not isinstance(node,list):raise ValueError('Conflicting object/list references; provide a sample manually.')
            if key>9:raise ValueError('Sample array indices must be below 10.')
            while len(node)<=key:node.append(None)
        elif not isinstance(node,dict):raise ValueError('Conflicting field structures; provide a sample manually.')
        if len(path)==1:node[key]=value;return
        existing=node[key] if isinstance(node,list) else node.get(key)
        if existing is None:
            existing=[] if isinstance(path[1],int) else {}
            node[key]=existing
        put(existing,path[1:],value)
    for path,reference in paths:
        if len(path)>20:raise ValueError('Sample field nesting exceeds 20 levels.')
        destination=data
        if direction=='REQUEST' and path[0] in ('addProps','header','headers'):
            destination=props if path[0]=='addProps' else headers;path=path[1:]
        elif direction=='REQUEST' and path[0]=='request':path=path[1:]
        if not path:continue
        name=str(path[-1]).lower()
        numeric=bool(re.search(re.escape(reference)+r'\?(?:number|c)\b',expanded)) or name in ('amount','quantity','price','total','count','unitprice')
        value=10 if numeric else True if name in ('enabled','active','isactive') else 'DEMO_'+str(path[-1])
        put(destination,path,value)
    if not data:raise ValueError('No supported body field references found. Dynamic keys, helpers or scalar aliases may need a supplied sample.')
    def serialize(payload):
        if source_format=='JSON':return payload
        if source_format=='ISO':
            if any(not str(k).isdigit() or not 0<=int(k)<=128 or isinstance(v,(dict,list)) for k,v in payload.items()):
                raise ValueError('Textual ISO needs scalar numeric field keys (0–128); this template is not compatible.')
            return '\n'.join(f'{k}={v}' for k,v in payload.items())
        if not re.fullmatch(r'[A-Za-z_][\w.-]*',xml_root):raise ValueError('Use an XML root name without a namespace prefix.')
        root=etree.Element(xml_root)
        def append(parent,key,value):
            if isinstance(value,list):
                for item in value:append(parent,key,item)
                return
            if not re.fullmatch(r'[A-Za-z_][\w.-]*',str(key)):raise ValueError('XML sample field names require simple element names; attributes/namespaces need manual input.')
            node=etree.SubElement(parent,key)
            if isinstance(value,dict):
                for k,v in value.items():append(node,k,v)
            else:node.text=str(value).lower() if isinstance(value,bool) else '' if value is None else str(value)
        for k,v in payload.items():append(root,k,v)
        return etree.tostring(root,encoding='unicode',pretty_print=True)
    variants=[('Inferred sample',data)]
    def empty(value):
        return [] if isinstance(value,list) else {k:empty(v) for k,v in value.items()} if isinstance(value,dict) else value
    empty_data=empty(data)
    if empty_data!=data:variants.append(('Empty collections',empty_data))
    missing=copy.deepcopy(data);missing.pop(next(iter(missing)))
    variants.append(('Missing field probe',missing))
    return {'source_format':source_format,'direction':direction,'warnings':warnings,'inferred_references':refs,
            'cases':[{'name':name,'input_payload':({'inputRequest':serialize(value),'headers':headers,'additionalProperties':props} if direction=='REQUEST' else serialize(value)),'additionalProperties':props,'headers':headers,
                      'verified':False} for name,value in variants]}
