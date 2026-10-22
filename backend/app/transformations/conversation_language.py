"""Complete conversational aliases only. This is not a trained language model."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re


@_log_traced('app.transformations.conversation_language.direction_reply', level=10)
def direction_reply(text):
    match=re.fullmatch(r"\s*(?:(?:it is|it's|this is|use|for|make it|i need)\s+)?(?:a\s+)?(request|response)(?:\s+transformation)?[.!?]?\s*",text,re.I)
    return match[1].lower() if match else None


@_log_traced('app.transformations.conversation_language.normalize_conversation_command', level=10)
def normalize_conversation_command(message):
    lines=message.splitlines(keepends=True)
    fenced=False
    prefix=r'(?:(?:can you|could you|would you)\s+)?(?:please\s+)?'
    for index,line in enumerate(lines):
        if '```' in line:
            if line.count('```')%2:fenced=not fenced
            continue
        if fenced:continue
        text=line.strip()
        ending='\n' if line.endswith('\n') else ''
        match=re.fullmatch(prefix+r'(generate|create|make|build|fix|repair)\s+(?:me\s+)?(?:a\s+|the\s+|this\s+|my\s+)?(request|response)\s+(?:template|transformation)(?:\s+please)?[.!?]?',text,re.I)
        if match:
            action='fix' if match[1].lower() in ('fix','repair') else 'generate'
            lines[index]=action+' '+match[2].lower()+ending
        elif re.fullmatch(prefix+r'(?:test|run)\s+(?:this|it|the template|this transformation|the transformation)(?:\s+please)?[.!?]?',text,re.I):
            lines[index]='test'+ending
        else:
            # Require two explicit paths. Never infer a field from vague prose.
            path=r'([A-Za-z_][A-Za-z0-9_.*\[\]-]*(?:\.[A-Za-z0-9_.*\[\]-]+)*)'
            mapping=re.fullmatch(prefix+r'(?:use|map)\s+'+path+r'\s+(?:for|to)\s+'+path+r'[!?]?',text,re.I)
            if mapping:
                lines[index]='map '+mapping[1]+' to '+mapping[2]+ending
    return ''.join(lines)
