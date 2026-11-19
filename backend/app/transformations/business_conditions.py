"""Validate and compile bounded business conditions without accepting raw FTL."""
import math

OPERATORS={'eq','ne','gt','gte','lt','lte','in','not_in','exists','not_exists'}


def scalar(value):
    if isinstance(value,(dict,list)) or (isinstance(value,float) and not math.isfinite(value)):
        raise ValueError('Condition values must be finite scalars.')


def prepare(rules,sources,targets,fmt):
    prepared={}
    for rule in rules:
        if set(rule)-{'target','branches','else'} or not {'target','branches','else'}<=set(rule):
            raise ValueError('Each condition requires target, branches and else only.')
        target=rule['target']
        if not isinstance(target,str) or target not in targets:
            raise ValueError('Condition target must be an exact target leaf path.')
        path,sample=targets[target]
        if path in prepared:raise ValueError('Only one conditions entry is allowed per target.')
        branches=rule['branches']
        if not isinstance(branches,list) or not 1<=len(branches)<=10:
            raise ValueError('Provide 1 to 10 ordered branches per target.')
        for branch in branches:
            if not isinstance(branch,dict) or set(branch)-{'field','operator','value','then'} or not {'field','operator','then'}<=set(branch):
                raise ValueError('Each branch requires field, operator and then; value is needed for comparisons.')
            field=branch['field'];operator=branch['operator']
            if not isinstance(field,str) or field not in sources:raise ValueError('Condition field must be an exact source leaf path.')
            if not isinstance(operator,str) or operator not in OPERATORS:raise ValueError('Unsupported condition operator.')
            if operator not in ('exists','not_exists'):
                if 'value' not in branch:raise ValueError('Comparison branches require value.')
                value=branch['value']
                if operator in ('in','not_in'):
                    if not isinstance(value,list) or not 1<=len(value)<=50:raise ValueError('in/not_in requires 1 to 50 values.')
                    for v in value:scalar(v)
                    if any(v is None for v in value):raise ValueError('Use not_exists for missing values.')
                else:
                    scalar(value)
                    if value is None:raise ValueError('Use exists/not_exists for missing values.')
                if operator in ('gt','gte','lt','lte') and (type(value) not in (int,float)):
                    raise ValueError('Numeric comparison operators require a numeric value.')
        for value in [rule['else']]+[b['then'] for b in branches]:
            scalar(value)
            if fmt=='ISO' and isinstance(value,str) and ('\n' in value or '\r' in value):
                raise ValueError('Textual ISO branch values must not contain line breaks.')
            if fmt=='JSON' and value is not None:
                if isinstance(sample,bool) and not isinstance(value,bool):raise ValueError('Boolean target branches require booleans or null.')
                if type(sample) in (int,float) and type(value) not in (int,float):raise ValueError('Numeric target branches require numbers or null.')
                if isinstance(sample,str) and not isinstance(value,str):raise ValueError('String target branches require strings or null.')
        prepared[path]=rule
    return prepared


def render(rule,expression,constant,literal,source_format,source_paths):
    def text(value):
        return str(value).lower() if isinstance(value,bool) else str(value)
    def predicate(branch):
        field=branch['field'];expr=expression(source_paths[field]);op=branch['operator']
        exists=f'({expr})??'
        if source_format=='XML' and source_paths[field][0] not in ('header','headers','addProps'):
            exists=f'({expr})?has_content && ({expr})?size == 1'
        if op=='exists':return '('+exists+')'
        if op=='not_exists':return '!('+exists+')'
        value=branch['value']
        left=expr+'?string'
        if op in ('in','not_in'):
            choices='['+','.join(literal(text(v)) for v in value)+']'
            test=choices+'?seq_contains('+left+')'
            if op=='not_in':test='!('+test+')'
        elif type(value) in (int,float):
            exists+=f' && {left}?matches("[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?")'
            compare={'eq':'==','ne':'!=','gt':'gt','gte':'gte','lt':'lt','lte':'lte'}[op]
            test=f'{expr}?number {compare} {value}'
        else:
            test=left+(' == ' if op=='eq' else ' != ')+literal(text(value))
        return '('+exists+' && ('+test+'))'
    out=''
    for index,branch in enumerate(rule['branches']):
        out+=('<#if ' if index==0 else '<#elseif ')+predicate(branch)+'>'+constant(branch['then'])
    return out+'<#else>'+constant(rule['else'])+'</#if>'
