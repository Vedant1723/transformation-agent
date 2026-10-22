"""Explicit paste-in-chat protocol. Payload text is data, never instructions."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy
import json
import re
from app.schemas.transformations import TransformationChatRequest
from app.transformations.workbench import normalize, leaves, path_name, parse_instructions
from app.transformations.source_presets import ALIASES, preset_payload
from app.transformations.conversation_language import normalize_conversation_command
from app.transformations.collection_filters import parse_filter_message,filter_key


class MissingDirection(ValueError):
    pass


class MissingPayload(ValueError):
    pass


@_log_traced('app.transformations.chat_intake.parse_pasted_message', level=10)
def parse_pasted_message(message, previous=None):
    message = normalize_conversation_command(message)
    operation_match = re.match(r'^\s*(?:please\s+)?(?:generate|make|create)(?:\s+(?:a|the))?(?:\s+transformation\s+for)?\s+(lookupdetails|lookup|processtxn|txnstatus|createaccount|accountstatus)\b(?:\s+(request|response))?[ \t]*(?:\n|$)', message, re.I)
    operation = ALIASES[operation_match[1].lower()] if operation_match else None
    if operation_match:
        message = 'generate' + (' ' + operation_match[2] if operation_match[2] else '') + '\n' + message[operation_match.end():]
    explicit_generation = bool(re.match(r'^\s*generate\s+(?:request|response)[ \t]*(?:\n|$)', message, re.I))
    if '```' not in message and not operation and not explicit_generation:
        return None
    # Match complete blocks before reading prose; never rewrite text inside payloads.
    roles='source|target|template|headers|additionalProperties'
    pattern = rf'(?:(?:^|\n)[ \t]*({roles})(?:[ \t]+payload)?[ \t]*:?[ \t]*\n[ \t]*```(?:json|xml|iso|ftl|freemarker)?[ \t]*\n|```({roles})[ \t]*\n)([\s\S]*?)```'
    blocks = list(re.finditer(pattern, message, re.I))
    if (not blocks and not operation and not explicit_generation) or message.count('```') != len(blocks) * 2:
        raise ValueError('Use fenced blocks labelled source, target or template. See the chat example.')
    rest = message
    values = {}
    for block in reversed(blocks):
        key = (block[1] or block[2]).lower()
        if key in values or not block[3].strip():
            raise ValueError('Supply one nonempty block per source, target or template.')
        values[key] = block[3].strip()
        rest = rest[:block.start()] + rest[block.end():]
    lines=[line.strip() for line in rest.splitlines() if line.strip()]
    mapping_rules={}
    validation_lines=[]
    filter_rules={}
    commands=[]
    for line in lines:
        filter_rule=parse_filter_message(line)
        if filter_rule:
            field=filter_key(filter_rule)
            if field in filter_rules and filter_rules[field]!=filter_rule:
                raise ValueError('Conflicting filters for the same field. Supply one filter per field.')
            filter_rules[field]=filter_rule
            continue
        mapping=re.fullmatch(r'(?:please\s+)?map\s+(\S+)\s+to\s+(\S+)',line,re.I)
        if mapping:
            if mapping[2] in mapping_rules and mapping_rules[mapping[2]]!=mapping[1]:
                raise ValueError('Conflicting mappings for the same target; choose one source.')
            mapping_rules[mapping[2]]=mapping[1]
        elif re.match(r'^(?:require|required)\s|^\S+\s+(?:required|email|min|max|min_length|max_length|length|regex|enum|type)(?:\s|$)',line,re.I):
            validation_lines.append(line)
        else:
            commands.append(line)
    command = re.fullmatch(r'\s*(?:please\s+)?(generate|make|create|fix)(?:\s+(?:this|a|the))?(?:\s+(?:(request|response)(?:\s+transformation)?|transformation(?:\s+(request|response))?))?[.!]?\s*', ' '.join(commands), re.I)
    if not command:
        raise ValueError('Start with “generate request”, “generate response”, or “fix request/response”. Send mapping or validation instructions in the next message; other prose is not silently ignored.')
    action = 'fix' if command[1].lower() == 'fix' else 'generate'
    context = copy.deepcopy(previous) if previous else {}
    supplied_direction=command[2] or command[3]
    direction = supplied_direction.upper() if supplied_direction else context.get('direction')
    if not direction:
        raise MissingDirection('Specify request or response so the correct body paths are used.')
    using_preset = bool(operation and 'source' not in values)
    if using_preset:
        values['source'] = json.dumps(preset_payload(operation, direction))
    # New examples must not silently inherit old mappings, validations or metadata.
    if 'source' in values or 'target' in values:
        context = {'direction': direction, 'source': context.get('source'), 'target': context.get('target')}
    context['direction'] = direction
    for key,field in [('headers','headers'),('additionalproperties','additionalProperties')]:
        if key in values:
            if direction!='REQUEST':
                raise ValueError('Headers and additionalProperties blocks are request-only.')
            def unique_pairs(pairs):
                result={}
                for name,value in pairs:
                    if name in result:
                        raise ValueError('Duplicate metadata key; choose one value.')
                    result[name]=value
                return result
            try:
                metadata=json.loads(values[key],object_pairs_hook=unique_pairs)
            except json.JSONDecodeError:
                _log_exception('app.transformations.chat_intake:94', handled=True)
                raise ValueError('Metadata must be a valid JSON object.') from None
            if not isinstance(metadata,dict):
                raise ValueError('Metadata must be a JSON object, not an array or scalar.')
            context[field]=metadata
    for key in ('source', 'target'):
        if key in values:
            context[key] = {'format': 'JSON', 'payload': values[key]}
    if not context.get('source') or not context.get('target'):
        missing=[key for key in ('source','target') if not context.get(key)]
        raise MissingPayload('Please add a '+ ' and '.join(missing)+' block. I will reuse the payload already supplied.')
    if action == 'generate' and 'template' in values:
        raise ValueError('Use “fix” when supplying an existing template; it will not be silently replaced.')
    if action == 'fix' and 'template' not in values:
        raise ValueError('Include a template block to fix an existing transformation.')
    if mapping_rules:
        if action=='fix':
            raise ValueError('Fix runs the original template first. Send mapping changes separately after reviewing its test.')
        context['mappings']=mapping_rules
    if filter_rules:
        if action=='fix':
            raise ValueError('Fix runs the original template first. Send filter changes separately after reviewing its test.')
        context['filters']=list(filter_rules.values())
    validated=TransformationChatRequest(**context)
    if validation_lines:
        if action=='fix':
            raise ValueError('Fix runs the original template first. Send validation changes separately after reviewing its test.')
        fields={path_name(path) for path,value in leaves(normalize(validated.source.payload,validated.source.format))}
        for prefix,metadata in [('header',validated.headers),('addProps',validated.additionalProperties)]:
            fields.update(path_name(path) for path,value in leaves({prefix:metadata}))
        rules=parse_instructions('\n'.join(validation_lines),fields)
        merged={}
        for rule in rules:
            key=(rule['field'],rule['type'])
            if key in merged and merged[key]!=rule:
                raise ValueError('Conflicting validation rules for the same field and type.')
            merged[key]=rule
        validated.validations=list(merged.values())
    return {'command': action, 'context': validated.model_dump(), 'template': values.get('template'),
            'source_preset': operation if using_preset else None}
