"""Bounded, explicit instruction parsing shared by direct generation clients.

This is a domain parser, not model-generated interpretation. Ambiguity is an error.
"""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re
from app.transformations.collection_filters import parse_filter_message, filter_key
from app.transformations.conversation_language import normalize_conversation_command


@_log_traced('app.transformations.generation_instructions.apply_instructions', level=10)
def apply_instructions(request, sources, targets):
    mappings=dict(request.mappings)
    filters=list(request.filters)
    remaining=[]
    def path(value, available):
        normalized=re.sub(r'\[(\d+)\]',r'.\1',value)
        if normalized not in available:
            raise ValueError(f'Unknown field {value!r}. Use an exact field path from the payload.')
        return normalized
    # Preserve semicolons in regex/JSON literals; commands can be one per line.
    for line in request.message.splitlines():
        text=normalize_conversation_command(line.strip()).strip()
        if not text:continue
        match=re.fullmatch(r'map\s+(\S+)\s+to\s+(\S+)',text,re.I)
        if match:
            source=path(match[1],sources);target=path(match[2],targets)
            existing=mappings.get(target)
            if existing is not None and existing!=source:
                raise ValueError(f'Conflicting mapping for {target}: review the instruction and mappings field.')
            mappings[target]=source
            continue
        rule=parse_filter_message(text)
        if rule:
            rule['field']=path(rule['field'],sources)
            previous=next((r for r in filters if filter_key(r)==filter_key(rule)),None)
            if previous and previous!=rule:raise ValueError('Conflicting collection filter; review the explicit filters and instructions.')
            if not previous:filters.append(rule)
            continue
        match=re.fullmatch(r'(\S+)\s+(?:must be|should be|is)\s+(required|mandatory)',text,re.I)
        if match:text=path(match[1],sources)+' required'
        match=re.fullmatch(r'(\S+)\s+(?:must be|should be)\s+(at least|at most)\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))',text,re.I)
        if match:text=path(match[1],sources)+(' min ' if match[2].lower()=='at least' else ' max ')+match[3]
        remaining.append(text)
    if len(filters)>20:raise ValueError('At most 20 collection filters are supported.')
    return request.model_copy(update={'mappings':mappings,'filters':filters,'message':'\n'.join(remaining)})
