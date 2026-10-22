"""Explicit string equality filters; values are data, not template code."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import re
import math

OPERATORS={'>':'gt','>=':'gte','<':'lt','<=':'lte','==':'eq','!=':'ne'}

@_log_traced('app.transformations.collection_filters.remove_filter', level=10)
def remove_filter(text,existing):
    """Return a new rule list, None for other messages; never mutate existing."""
    if not re.match(r'\s*(?:please\s+)?remove\s+filter\b',text,re.I):return None
    match=re.fullmatch(r'\s*(?:please\s+)?remove\s+filter\s+(\S+)\s+(in|>=|<=|==|!=|>|<)\s*',text,re.I)
    if not match:raise ValueError('Specify the exact field and operator, for example: remove filter items[0].amount >=')
    field=re.sub(r'\[(\d+)\]',r'.\1',match[1])
    operator=OPERATORS.get(match[2],match[2].lower())
    key=(field,operator)
    if not any(filter_key(rule)==key for rule in existing):
        raise ValueError('No active filter matches that field and operator. Check the saved active conditions.')
    return [rule for rule in existing if filter_key(rule)!=key]

@_log_traced('app.transformations.collection_filters.filter_key', level=10)
def filter_key(rule):
    return (rule['field'],rule.get('operator','in'))

@_log_traced('app.transformations.collection_filters.describe_filter', level=10)
def describe_filter(rule):
    operator=rule.get('operator','in')
    return rule['mode']+' '+rule['field']+' '+operator+' '+json.dumps(rule['values'])

@_log_traced('app.transformations.collection_filters.validate_filter', level=10)
def validate_filter(rule):
    if set(rule)-{'field','mode','values','operator'} or not {'field','mode','values'}<=set(rule) or rule['mode'] not in ('include','exclude') or not isinstance(rule['field'],str):
        raise ValueError('Filter needs field, include/exclude mode and values.')
    values=rule['values']
    if rule.get('operator','in')!='in':
        if rule.get('operator') not in OPERATORS.values():raise ValueError('Unsupported numeric comparison operator.')
        if not isinstance(values,list) or len(values)!=1 or isinstance(values[0],bool) or not isinstance(values[0],(int,float)) or abs(values[0])>10**15 or not math.isfinite(values[0]):
            raise ValueError('Numeric filters require one finite number between -1e15 and 1e15.')
        return
    if not isinstance(values,list) or not 1<=len(values)<=100 or any(not isinstance(v,str) or len(v)>200 for v in values):
        raise ValueError('Supply 1–100 string filter values, each at most 200 characters.')

@_log_traced('app.transformations.collection_filters.parse_filter_message', level=10)
def parse_filter_message(text):
    numeric=re.fullmatch(r'(?:please\s+)?(exclude|include only)\s+items\s+where\s+(\S+)\s*(>=|<=|==|!=|>|<)\s*(\S+)\s*',text,re.I)
    if numeric:
        try:value=json.loads(numeric[4])
        except ValueError:_log_exception('app.transformations.collection_filters:43', handled=True); raise ValueError('Use a JSON number after the comparison, for example >= 100.') from None
        rule={'field':re.sub(r'\[(\d+)\]',r'.\1',numeric[2]),'mode':'exclude' if numeric[1].lower()=='exclude' else 'include','operator':OPERATORS[numeric[3]],'values':[value]}
        validate_filter(rule)
        return rule
    match=re.fullmatch(r'(?:please\s+)?(exclude|include only)\s+items\s+where\s+(\S+)\s+in\s+(\[.*\])\s*',text,re.I|re.S)
    if not match:return None
    try:values=json.loads(match[3])
    except ValueError:_log_exception('app.transformations.collection_filters:50', handled=True); raise ValueError('Filter values must be a JSON string array.') from None
    field=re.sub(r'\[(\d+)\]',r'.\1',match[2])
    rule={'field':field,'mode':'exclude' if match[1].lower()=='exclude' else 'include','values':values}
    validate_filter(rule)
    return rule

@_log_traced('app.transformations.collection_filters.parse_filter_batch', level=10)
def parse_filter_batch(text):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if not any(re.match(r'(?:please\s+)?(?:exclude|include only)\s+items\b',line,re.I) for line in lines):return []
    rules={}
    for line in lines:
        rule=parse_filter_message(line)
        if rule is None:raise ValueError('Use one complete filter per line. Extra instructions were not applied.')
        key=filter_key(rule)
        if key in rules and rules[key]!=rule:raise ValueError('Conflicting filters for the same field and operator.')
        rules[key]=rule
    if len(rules)>20:raise ValueError('Use at most 20 collection filters.')
    return list(rules.values())
