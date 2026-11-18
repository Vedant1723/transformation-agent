"""Read-only field discovery using the same normalization and paths as generation."""
import json
from collections import Counter
from lxml import etree
from app.core.observability import traced
from app.transformations.workbench import normalize, path_name, xml_root

VALIDATIONS = [
    {'type':'required','valueType':'none'},
    {'type':'min','valueType':'number'},
    {'type':'max','valueType':'number'},
    {'type':'length','valueType':'nonnegative_integer'},
    {'type':'min_length','valueType':'nonnegative_integer'},
    {'type':'max_length','valueType':'nonnegative_integer'},
    {'type':'regex','valueType':'string'},
    {'type':'email','valueType':'none'},
    {'type':'enum','valueType':'comma_separated_string'},
    {'type':'type','valueType':'string','options':['string','number','boolean']},
]


def typename(value):
    if isinstance(value,dict):return 'object'
    if isinstance(value,list):return 'array'
    if value is None:return 'null'
    if isinstance(value,bool):return 'boolean'
    if isinstance(value,(int,float)):return 'number'
    return 'string'


@traced('app.services.mapping_discovery.discover', level=20)
def discover(request):
    warnings=[]; count=0
    def tree(payload,fmt,side,metadata=None):
        nonlocal count
        if len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))>250000:
            raise ValueError('Mapping discovery accepts up to 250 KB per payload.')
        try:normalized=dict(normalize(payload,fmt))
        except etree.XMLSyntaxError as exc:raise ValueError(f'{side} contains invalid XML.') from exc
        if metadata:
            for key,value in metadata.items():
                if not value:continue
                if key in normalized or (key=='headers' and 'header' in normalized):
                    raise ValueError(f'{side} payload conflicts with request metadata {key}.')
                normalized[key]=value
        flat=[]; by_path={}
        def walk(key,value,path):
            nonlocal count
            count+=1
            if count>2000 or len(path)>20:raise ValueError('Mapping discovery supports at most 2000 nodes and 20 nesting levels.')
            kind=typename(value)
            node={'key':str(key),'path':path_name(path),'type':kind,'mappable':kind not in ('object','array')}
            flat.append(node);by_path[path]=node
            if isinstance(value,(dict,list)):
                items=value.items() if isinstance(value,dict) else enumerate(value)
                node['children']=[walk(k,v,path+(k,)) for k,v in items]
                if not node['children']:warnings.append(f'{side} {node["path"]}: empty {kind}; provide an example child to discover its fields.')
            return node
        nodes=[walk(k,v,(k,)) for k,v in normalized.items()]
        if fmt=='XML':
            def attributes(element,path):
                nonlocal count
                node=by_path.get(path)
                if node is not None:
                    for name in element.attrib:
                        count+=1
                        if count>2000:raise ValueError('Mapping discovery supports at most 2000 nodes.')
                        attribute={'key':'@'+name,'path':path_name(path+('@'+name,)),
                                   'type':'string','mappable':False}
                        node.setdefault('children',[]).append(attribute)
                    if element.attrib: warnings.append(f'{side} {path_name(path)}: XML attributes are shown but are not supported as mapping fields by the generator.')
                    if len(element) and (element.text or '').strip():
                        node.setdefault('children',[]).append({'key':'#text','path':path_name(path+('#text',)),'type':'string','mappable':False})
                        warnings.append(f'{side} {path_name(path)}: mixed XML text is not supported as a mapping field.')
                children=[child for child in element if isinstance(child.tag,str)]
                counts=Counter(child.tag for child in children);seen=Counter()
                for child in children:
                    child_path=path+(child.tag,)
                    if counts[child.tag]>1:child_path+=(seen[child.tag],)
                    seen[child.tag]+=1;attributes(child,child_path)
            root=xml_root(payload);attributes(root,(root.tag,))
        duplicate=Counter(n['path'] for n in flat if n['mappable'])
        for node in flat:
            if node['mappable'] and duplicate[node['path']]>1:
                node['mappable']=False
                warnings.append(f'{side} {node["path"]}: ambiguous dotted path; rename the conflicting key before mapping.')
        return nodes

    metadata={'headers':request.headers,'addProps':request.additionalProperties} if request.direction=='REQUEST' else None
    source=tree(request.source.payload,request.source.format,'Source',metadata)
    target=tree(request.target.payload,request.target.format,'Target')
    def paths(nodes):
        result=[]
        for node in nodes:
            if node['mappable']:
                result.append(node['path'])
            result.extend(paths(node.get('children',[])))
        return list(dict.fromkeys(result))
    return {'sourceFormat':request.source.format,'targetFormat':request.target.format,
            'sourcePayloadKeys':paths(source),'targetPayloadKeys':paths(target),
            'validations':VALIDATIONS,'validationField':'source path',
            'validationFailureActions':['stop','fallback'],
            'warnings':list(dict.fromkeys(warnings))}
