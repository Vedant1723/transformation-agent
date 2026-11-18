"""Bounded static sample inference; never claims a sample satisfies business rules."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re
from lxml import etree
from app.transformations.template_tools import REFERENCE


@_log_traced('app.transformations.payload_generator.generate_payload', level=10)
def generate_payload(template, source_format='JSON', direction='REQUEST', xml_root='root'):
    if source_format not in ('JSON', 'XML', 'ISO'):
        raise ValueError('source_format must be JSON, XML or ISO.')
    if direction not in ('REQUEST', 'RESPONSE'):
        raise ValueError('direction must be REQUEST or RESPONSE.')
    if not isinstance(template, str) or not template.strip() or len(template)>50000:
        raise ValueError('Provide a template between 1 and 50000 characters.')
    clean=re.sub(r'<#--[\s\S]*?-->','',template)
    warnings=['Synthetic input inferred from static references. Review values and run Test; validation rules and dynamic expressions may require edits.']
    # Resolve aliases within their lexical loop scope, including scalar lists.
    scopes=[]; chunks=[]; loop_paths=[]
    def expand(text):
        aliases={}
        for scope in scopes:aliases.update(scope)
        for alias,path in aliases.items():
            text=re.sub(r'\b'+re.escape(alias)+r'\b',lambda _:path,text)
        return text
    for part in re.split(r'(<#list\b[^>]*>|</#list\s*>)',clean):
        if part.startswith('<#list'):
            match=re.fullmatch(r'<#list\s+(.+?)\s+as\s+(\w+)\s*>',part)
            if not match:raise ValueError('Unsupported list expression; provide a sample manually.')
            path=expand(match[1]).strip()
            path=re.sub(r'!\[\]$', '', path).strip().strip('()')
            if not REFERENCE.fullmatch(path) or not path.startswith(('body.','body[')):
                raise ValueError('Dynamic or filtered list sources require a supplied sample.')
            path+='[0]';loop_paths.append(path)
            scopes.append({match[2]:path})
        elif part.startswith('</#list'):
            if not scopes:raise ValueError('Unexpected closing list directive.')
            scopes.pop()
        else:chunks.append(expand(part))
    if scopes:raise ValueError('Unclosed list directive.')
    expanded=''.join(chunks)
    refs=sorted(set(REFERENCE.findall(expanded)) | set(loop_paths))
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
    data=None;props={};headers={}
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
        destination=None
        if direction=='REQUEST' and path[0] in ('addProps','header','headers'):
            destination=props if path[0]=='addProps' else headers;path=path[1:]
        elif direction=='REQUEST' and path[0]=='request':path=path[1:]
        if not path:continue
        if destination is None:
            if data is None:data=[] if isinstance(path[0],int) else {}
            destination=data
        name=str(path[-1]).lower()
        numeric=bool(re.search(re.escape(reference)+r'\?(?:number|c)\b',expanded)) or name in ('amount','quantity','price','total','count','unitprice')
        value=10 if numeric else True if name in ('enabled','active','isactive') else 'DEMO_'+str(path[-1])
        put(destination,path,value)
    if data is None:
        if props or headers:data={}
        else:raise ValueError('No supported body field references found. Dynamic keys or helpers may need a supplied sample.')
    def serialize(payload):
        if source_format=='JSON':return payload
        if source_format=='ISO':
            if not isinstance(payload,dict):raise ValueError('Textual ISO requires quoted numeric field keys, not array indices.')
            if any(not str(k).isdigit() or not 0<=int(k)<=128 or isinstance(v,(dict,list)) for k,v in payload.items()):
                raise ValueError('Textual ISO needs scalar numeric field keys (0–128); this template is not compatible.')
            return '\n'.join(f'{k}={v}' for k,v in payload.items())
        if not re.fullmatch(r'[A-Za-z_][\w.-]*',xml_root):raise ValueError('Use an XML root name without a namespace prefix.')
        root=etree.Element(xml_root)
        if not isinstance(payload,dict):raise ValueError('XML requires named elements, not a top-level array.')
        def append(parent,key,value):
            if isinstance(value,list):
                for item in value:append(parent,key,item)
                return
            if str(key).startswith('@'):
                attr=str(key)[1:]
                if not re.fullmatch(r'[A-Za-z_][\w.-]*',attr) or isinstance(value,(dict,list)):
                    raise ValueError('XML attributes require a simple name and scalar value.')
                parent.set(attr,str(value));return
            if not re.fullmatch(r'[A-Za-z_][\w.-]*',str(key)):raise ValueError('XML sample field names require simple element names; namespaces need manual input.')
            node=etree.SubElement(parent,key)
            if isinstance(value,dict):
                for k,v in value.items():append(node,k,v)
            else:node.text=str(value).lower() if isinstance(value,bool) else '' if value is None else str(value)
        for k,v in payload.items():append(root,k,v)
        return etree.tostring(root,encoding='unicode',pretty_print=True)
    return {'source_format':source_format,'direction':direction,'warnings':warnings,'inferred_references':refs,
            'input_payload':({'inputRequest':serialize(data),'inputHeaders':headers,'additionalProperties':props}
                             if direction=='REQUEST' else serialize(data)),
            'verified':False}
