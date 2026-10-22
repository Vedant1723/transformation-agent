"""Read-only, bounded summary of saved requirements; not inferred intent."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
from app.transformations.collection_filters import describe_filter

SUMMARY_COMMANDS={'show requirements','summarize requirements','what are the current requirements','what are the current requirements?'}

@_log_traced('app.transformations.conversation_summary.requirements_summary', level=10)
def requirements_summary(state):
    context=state.get('context') or {}
    lines=['Saved transformation requirements (not model training):']
    if not context:lines.append('No complete source/target context has been saved yet.')
    else:
        lines.append('Direction: '+context.get('direction','not selected'))
        for key in ('source','target'):
            payload=context.get(key) or {}
            lines.append(key.title()+': '+payload.get('format','unknown')+' sample '+('available' if 'payload' in payload else 'missing'))
        for key in ('headers','additionalProperties'):
            lines.append(key+': '+str(len(context.get(key) or {}))+' saved keys (values not repeated here).')
        mappings=context.get('mappings') or {}
        lines.append('Explicit mappings: '+str(len(mappings)))
        for target,source in list(mappings.items())[:20]:lines.append('  '+source+' -> '+target)
        rules=context.get('validations') or []
        lines.append('Validations: '+str(len(rules)))
        for rule in rules[:20]:lines.append('  '+str(rule.get('field',''))+' · '+str(rule.get('type',''))+' · '+str(rule.get('on_failure','stop')))
        filters=context.get('filters') or []
        lines.append('Collection filters: '+str(len(filters)))
        for rule in filters[:20]:lines.append('  '+describe_filter(rule))
    revision=next((r for r in state.get('revisions',[]) if r['id']==state.get('current')),None)
    if revision:
        result=revision.get('test')
        status='not tested'
        if result:
            status='stale — inputs changed; test again' if revision.get('test_context')!=context else 'passed sample execution' if result.get('passed') else 'failed sample execution'
        lines.append(f'Current version: {revision["id"]}; test: {status}.')
    else:lines.append('No generated version yet.')
    if state.get('pending_direction_message'):lines.append('Waiting for request/response direction. Your pending message is still saved.')
    if state.get('pending_payload_message'):lines.append('Waiting for missing payload blocks. Your pending message is still saved.')
    lines.append('This summary does not change inputs, rules or versions. Passing a sample is not production certification.')
    return '\n'.join(lines)
