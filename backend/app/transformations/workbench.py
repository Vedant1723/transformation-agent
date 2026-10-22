"""Preview-oriented mapping and validation for the authenticated workbench."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import math
import re
from collections import Counter

from lxml import etree

from app.transformations.structure import collections, plan_loops, choose
from app.transformations.request_context import setup
from app.transformations.json_validation import strict_json, finite_values

PREAMBLE = '<#setting number_format="computer">\n<#setting boolean_format="c">\n<#assign body = JsonUtils.getJsonAsMap(input)>\n'


@_log_traced('app.transformations.workbench.literal', level=10)
def literal(value):
    # FreeMarker string literals interpolate ${...}; escape user literals.
    return json.dumps(str(value), ensure_ascii=False).replace('${', r'\${').replace('#{', r'\#{')


@_log_traced('app.transformations.workbench.xml_root', level=10)
def xml_root(payload):
    if not isinstance(payload, str) or '<!DOCTYPE' in payload.upper():
        raise ValueError('XML must be text without a DOCTYPE.')
    return etree.fromstring(payload.encode(), etree.XMLParser(resolve_entities=False, no_network=True))


@_log_traced('app.transformations.workbench.normalize', level=10)
def normalize(payload, fmt):
    fmt = fmt.upper()
    if fmt == 'XML':
        root = xml_root(payload)
        def convert(node):
            if not len(node):
                return node.text or ''
            result = {}
            counts = Counter(child.tag for child in node)
            for child in node:
                value = convert(child)
                if counts[child.tag] > 1:
                    result.setdefault(child.tag, []).append(value)
                else:
                    result[child.tag] = value
            return result
        return {root.tag: convert(root)}
    if fmt not in ('JSON', 'ISO'):
        raise ValueError('Supported formats: JSON, XML, ISO.')
    if isinstance(payload, str):
        if fmt == 'ISO' and not payload.lstrip().startswith('{'):
            fields = {}
            for line in payload.splitlines():
                if not line.strip():
                    continue
                key, separator, value = line.partition('=')
                key = key.strip()
                if not separator or key in fields:
                    raise ValueError('ISO input requires unique field=value lines, for example 0=0200 and 4=1250.')
                fields[key] = value
            payload = fields
        else:
            payload = strict_json(payload)
    if not isinstance(payload, dict):
        raise ValueError(f'{fmt} requires an object. ISO uses a JSON object keyed by field number.')
    if fmt == 'ISO' and any(not str(k).isdigit() or not 0 <= int(k) <= 128 for k in payload):
        raise ValueError('ISO field numbers must be between 0 and 128.')
    if fmt == 'ISO' and any(isinstance(value, (dict, list)) for value in payload.values()):
        raise ValueError('ISO field=value messages require scalar fields. Repeating groups need your partner subfield/packing specification; use JSON or XML for generic collections.')
    return finite_values(payload)


def leaves(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, path + (index,))
    else:
        yield path, value


@_log_traced('app.transformations.workbench.path_name', level=10)
def path_name(path):
    return '.'.join(map(str, path))


@_log_traced('app.transformations.workbench.expression', level=10)
def expression(path, source_format='JSON', direction='RESPONSE'):
    metadata = direction.upper() == 'REQUEST' and path and path[0] in ('addProps','header','headers')
    if metadata and path[0]=='header':path=('headers',)+tuple(path[1:])
    if source_format.upper() == 'XML' and not metadata:
        # body is already the document element, not a JSON map containing the root name.
        path = path[1:]
    if direction.upper() == 'REQUEST' and not metadata and (not path or path[0] != 'request' or len(path) == 1):
        path = ('request',) + path
    return 'body' + ''.join(f'[{part}]' if isinstance(part, int) else
                            '.' + part if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', part) else
                            f'[{literal(part)}]' for part in path)


@_log_traced('app.transformations.workbench.validation_blocks', level=10)
def validation_blocks(rules, paths, source_format='JSON', conditions=None, direction='RESPONSE', expression_fn=None):
    blocks = []
    for rule in rules:
        field, kind, value = rule.get('field'), rule.get('type'), rule.get('value', '')
        if field not in paths:
            raise ValueError(f'Validation field {field!r} is not present in the source sample.')
        expr = expression_fn(paths[field]) if expression_fn else expression(paths[field], source_format, direction)
        text = f'{expr}?string'
        if kind == 'required':
            condition = f'!({expr})?has_content || !({expr}?string?trim)?has_content'
        elif kind in ('min', 'max', 'min_length', 'max_length', 'length'):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('Validation bounds must be finite numbers.')
            if 'length' in kind and (number < 0 or not number.is_integer()):
                raise ValueError('Length must be a nonnegative integer.')
            left = text + '?length' if 'length' in kind else expr + '?number'
            op = '!=' if kind == 'length' else 'lt' if kind.startswith('min') else 'gt'
            condition = f'({left} {op} {number})'
            if 'length' not in kind:
                condition = f'!({text}?matches("[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?")) || ({condition})'
        elif kind in ('regex', 'email'):
            pattern = str(value) if kind == 'regex' else r'[^\s@]+@[^\s@]+\.[^\s@]+'
            re.compile(pattern)
            condition = f'!({text}?matches({literal(pattern)}))'
        elif kind == 'enum':
            choices = [x.strip() for x in str(value).split(',') if x.strip()]
            if not choices:
                raise ValueError('Allowed values must not be empty.')
            condition = f'!([{", ".join(literal(x) for x in choices)}]?seq_contains({text}))'
        elif kind == 'type':
            predicates = {'string': 'is_string', 'number': 'is_number', 'boolean': 'is_boolean'}
            if value not in predicates:
                raise ValueError('Type must be string, number, or boolean.')
            condition = f'!({expr}?{predicates[value]})'
            if source_format.upper() in ('XML', 'ISO') and value == 'number':
                condition = f'!({text}?matches("[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?"))'
            elif source_format.upper() in ('XML', 'ISO') and value == 'boolean':
                condition = f'!(["true", "false"]?seq_contains({text}))'
        else:
            raise ValueError(f'Unsupported validation: {kind}')
        if source_format.upper() == 'XML' and paths[field][0] not in ('addProps','header','headers') and not str(paths[field][0]).startswith('@'):
            # Missing XML children are empty node sequences: ?? alone is not an existence check.
            condition = f'!({expr})?has_content || ({expr})?size != 1 || ({condition})'
        elif kind != 'required':
            condition = f'!({expr})?? || ({condition})'
        action = rule.get('on_failure', 'stop')
        if action not in ('stop', 'fallback'):
            raise ValueError('Validation failure action must be stop or fallback.')
        if conditions is not None:
            conditions.append((rule, condition))
        message = rule.get('message') or f'{field}: {kind} validation failed' + (f' ({value})' if value != '' and kind not in ('required', 'email') else '')
        if action == 'stop':
            blocks.append(f'<#if {condition}><#stop {literal(message)}></#if>')
    return '\n'.join(blocks)


@_log_traced('app.transformations.workbench.parse_instructions', level=10)
def parse_instructions(message, fields):
    """Small explicit command language. Never silently ignore unknown instructions."""
    rules = []
    for command in re.split(r'[;\n]+', message.strip()):
        if not command.strip():
            continue
        command = command.strip()
        match = re.fullmatch(r'(?:require|required)\s+(.+)', command, re.I)
        if match:
            rules.append({'field': match[1].strip(), 'type': 'required'})
            continue
        match = re.fullmatch(r'(\S+)\s+(required|email|min|max|min_length|max_length|length|regex|enum|type)(?:\s+(.+))?', command, re.I)
        if not match:
            raise ValueError('Instruction not understood. Use “require msisdn” or “amount min 1”; separate commands with semicolons. You can also use the validation builder.')
        rules.append({'field': match[1], 'type': match[2].lower(), 'value': match[3] or ''})
    for rule in rules:
        if rule['field'] not in fields:
            raise ValueError(f"Unknown source field in instruction: {rule['field']}")
    return rules


@_log_traced('app.transformations.workbench.generate', level=10)
def generate(request, learned=None):
    from app.transformations.collection_filters import validate_filter
    source = normalize(request.source.payload, request.source.format)
    if request.direction == 'REQUEST':
        if request.additionalProperties:
            if 'addProps' in source:
                raise ValueError('Source already contains addProps. Move metadata into additionalProperties to avoid collisions.')
            source = {**source, 'addProps': request.additionalProperties}
        if request.headers:
            if 'header' in source or 'headers' in source:
                raise ValueError('Source already contains header. Move metadata into headers to avoid collisions.')
            source = {**source, 'headers': request.headers, 'header': request.headers}
    target = normalize(request.target.payload, request.target.format)
    sources = {path_name(p): (p, v) for p, v in leaves(source)}
    targets = {path_name(p): (p, v) for p, v in leaves(target)}
    source_lists = collections(source, request.source.format.upper() == 'XML')
    loops, loop_warnings = plan_loops(target, source_lists, request.target.format.upper() == 'XML')
    for plan in loops.values():
        if not any(p[:len(plan['prototype'])] == plan['prototype'] for p,v in sources.values()):
            raise ValueError(f"Collection {path_name(plan['source'])} has no sample fields. Add one representative item for generation; the generated loop accepts empty lists at runtime.")
    targets = {name:pair for name,pair in targets.items() if not any(
        isinstance(key[-1],int) and pair[0][:len(key)-1] == key[:-1] and
        len(pair[0]) >= len(key) and isinstance(pair[0][len(key)-1],int) and pair[0][len(key)-1] > 0
        for key in loops)}
    def owner(path):
        if path and path[0] in computed:
            return owner(computed[path[0]][1][0])
        matches = [key for key in source_lists if path[:len(key)] == key]
        return max(matches, key=len) if matches else None
    def target_owner(path):
        matches = [key for key in loops if path[:len(key)] == key]
        return loops[max(matches,key=len)]['source'] if matches else None
    if not sources or not targets:
        raise ValueError('Source and target must each contain at least one scalar field.')
    from app.transformations.generation_instructions import apply_instructions
    request = apply_instructions(request, sources, targets)
    overrides = request.mappings or {}
    if set(overrides) - set(targets):
        raise ValueError('A mapping refers to a target field that no longer exists. Regenerate mappings.')
    mapped, rows, warnings, computed = {}, [], list(loop_warnings), {}
    for name, (path, value) in targets.items():
        chosen = overrides.get(name)
        confidence, reason = 1.0, 'Explicit mapping'
        if chosen is None:
            chosen = (learned or {}).get(name)
            reason = 'Confirmed mapping from feedback'
            if chosen != '' and chosen not in sources and not (isinstance(chosen,str) and chosen.startswith('@')):
                pool = {n:pair for n,pair in sources.items() if owner(pair[0]) == target_owner(path) and not n.startswith('@') and not any(isinstance(p,int) and p>0 for p in pair[0])}
                chosen, confidence, reason = choose(path, pool)
                scalar = [n for n,pair in pool.items() if pair[0] == source_lists.get(target_owner(path))]
                if len(scalar) == 1:
                    chosen, confidence, reason = scalar[0], 1.0, 'Scalar collection item'
                # Known derived fields are explicit, reviewable suggestions, never inferred from values alone.
                kind = str(path[-1]).lower()
                required = ('firstname','lastname') if kind == 'fullname' else ('quantity','unitprice') if kind in ('totalprice','linetotal') else ()
                parts = [[pair[0] for n,pair in pool.items() if str(pair[0][-1]).lower() == field] for field in required]
                if not chosen and parts and all(len(part)==1 for part in parts) and parts[0][0][:-1] == parts[1][0][:-1]:
                    chosen = '@' + kind + ':' + '|'.join(path_name(part[0]) for part in parts)
                    computed[chosen] = (kind, [part[0] for part in parts])
                    sources[chosen] = ((chosen,), '')
                    confidence, reason = .9, 'Suggested full-name join' if kind == 'fullname' else 'Suggested quantity × unitPrice'
                    warnings.append(f'{name}: {reason}; verify this business rule before use.')
        if chosen and chosen.startswith('@') and chosen not in sources:
            kind, _, fields = chosen[1:].partition(':')
            parts = fields.split('|')
            if kind not in ('fullname','totalprice','linetotal') or len(parts)!=2 or any(p not in sources for p in parts):
                raise ValueError('The suggested calculation no longer matches the source sample. Clear the mapping and regenerate.')
            computed[chosen] = (kind, [sources[p][0] for p in parts])
            sources[chosen] = ((chosen,), '')
        if chosen and chosen not in sources:
            raise ValueError(f'Mapping source {chosen} was not found.')
        if chosen:
            mapped[path] = sources[chosen][0]
        else:
            warnings.append(f'{name}: no source mapping; sample value retained. Review before use.')
        rows.append({'target_field': name, 'source_field': chosen or '', 'confidence': confidence, 'reason': reason})
    rules = request.validations + parse_instructions(request.message, sources)
    active = []
    def source_expression(path):
        if path and path[0] in computed:
            kind, parts = computed[path[0]]
            a,b = [source_expression(part) for part in parts]
            if kind == 'fullname':
                return f'((({a})?has_content)?then({a}?string, "") + " " + (({b})?has_content)?then({b}?string, ""))?trim'
            return f'({a}?number * {b}?number)'
        for plan in reversed(active):
            prefix = plan['prototype']
            if path[:len(prefix)] == prefix:
                return plan['variable'] + expression(path[len(prefix):])[4:]
        return expression(path, request.source.format, request.direction)
    paths = {name:pair[0] for name,pair in sources.items()}
    for rule in request.filters:
        validate_filter(rule)
        if rule['field'] not in paths or owner(paths[rule['field']]) is None:
            raise ValueError('Filter field must be an exact scalar collection source field: '+rule['field'])
        if owner(paths[rule['field']]) not in [plan['source'] for plan in loops.values()]:
            raise ValueError('Filter collection is not mapped to a target list.')
    def blocks(selected, conditions=None):
        return validation_blocks(selected, paths, request.source.format, conditions, request.direction, source_expression)
    # Validate all rules now, but execute collection rules inside their corresponding loop.
    blocks(rules)
    guards = blocks([r for r in rules if owner(paths[r['field']]) is None])
    def start_loop(plan):
        iterable = source_expression(plan['source'])
        active.append(plan)
        predicates=[]
        for rule in request.filters:
            if owner(paths[rule['field']]) != plan['source']:continue
            expr=source_expression(paths[rule['field']])
            operator=rule.get('operator','in')
            valid=f'({expr})?has_content'
            if operator=='in':
                values='['+','.join(literal(value) for value in rule['values'])+']'
                contains=f'{values}?seq_contains({expr}?string)'
            else:
                from decimal import Decimal
                number=format(Decimal(str(rule['values'][0])),'f')
                compare={'gt':'gt','gte':'gte','lt':'lt','lte':'lte','eq':'==','ne':'!='}[operator]
                valid+=f' && {expr}?string?matches("[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?")'
                contains=f'({expr}?number {compare} {number})'
            predicates.append(f'({valid} && '+('!' if rule['mode']=='exclude' else '')+contains+')')
        if predicates:
            iterable=f'(({iterable})![])?filter({plan["variable"]} -> '+ ' && '.join(predicates)+')'
        inner_guards = blocks([r for r in rules if owner(paths[r['field']]) == plan['source']])
        return f'<#list ({iterable})![] as {plan["variable"]}>\n' + inner_guards

    def conditional(path, encode, constant, sample):
        """Render a scalar with inline IF/ELSEIF/default, preserving JSON/XML syntax."""
        original = encode(source_expression(mapped[path]))
        conditions = []
        blocks(rules, conditions)
        for rule, invalid in reversed(conditions):
            if rule.get('on_failure', 'stop') != 'fallback' or sources[rule['field']][0] != mapped[path]:
                continue
            fallback = rule.get('fallback_value', '')
            if request.target.format.upper() == 'JSON':
                if isinstance(sample, bool):
                    if fallback == '':
                        fallback = None
                    elif str(fallback).lower() not in ('true', 'false'):
                        raise ValueError('Boolean target fallback must be true, false, or blank (null).')
                    else:
                        fallback = str(fallback).lower() == 'true'
                elif isinstance(sample, (int, float)):
                    fallback = None if fallback == '' else float(fallback)
                    if fallback is not None and not math.isfinite(fallback):
                        raise ValueError('Numeric fallback must be finite.')
            branches = ''
            alternatives = rule.get('fallback_fields', [])
            if not isinstance(alternatives, list):
                raise ValueError('Fallback fields must be an ordered list of source paths.')
            for field in alternatives:
                if field not in sources:
                    raise ValueError(f'Fallback field {field!r} is not present in the source sample.')
                expr = source_expression(sources[field][0])
                valid = f'({expr})?has_content'
                if request.source.format.upper() == 'XML' and sources[field][0][0] not in computed and sources[field][0][0] not in ('addProps','header','headers'):
                    valid += f' && ({expr})?size == 1'
                valid += f' && ({expr}?string?trim)?has_content'
                # Apply the selected validation to alternatives too (including length and ranges).
                alternative_conditions = []
                blocks([{**rule, 'field': field}], alternative_conditions)
                valid += f' && !({alternative_conditions[0][1]})'
                if request.target.format.upper() == 'JSON' and isinstance(sample, bool):
                    valid += f' && ["true", "false"]?seq_contains({expr}?string)'
                elif request.target.format.upper() == 'JSON' and isinstance(sample, (int, float)):
                    valid += f' && {expr}?string?matches("[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?")'
                branches += ('<#if ' if not branches else '<#elseif ') + valid + '>' + encode(expr)
            tail = constant(fallback)
            if branches:
                tail = branches + '<#else>' + tail + '</#if>'
            valid_original = '!(' + invalid + ')'
            if rule['type'] == 'required':
                expr = source_expression(mapped[path])
                valid_original = f'({expr})?has_content'
                if request.source.format.upper() == 'XML' and mapped[path][0] not in computed and mapped[path][0] not in ('addProps','header','headers'):
                    valid_original += f' && ({expr})?size == 1'
                valid_original += f' && ({expr}?string?trim)?has_content'
            original = '<#if ' + valid_original + '>' + original + '<#else>' + tail + '</#if>'
        return original

    def render_json(value, path=()):
        if isinstance(value, dict):
            return '{' + ',\n'.join(json.dumps(k) + ': ' + render_json(v, path + (k,)) for k, v in value.items()) + '}'
        if isinstance(value, list):
            if path + (0,) in loops:
                begin = start_loop(loops[path+(0,)])
                content = render_json(value[0], path+(0,))
                active.pop()
                return '[' + begin + content + '<#sep>,</#sep></#list>]'
            return '[' + ','.join(render_json(v, path + (i,)) for i, v in enumerate(value)) + ']'
        if path not in mapped:
            # Constants are emitted via a literal to avoid template injection.
            return '${' + literal(json.dumps(value, ensure_ascii=False)) + '}'
        def constant(v):
            if v == '' or v is None:
                return json.dumps(v)
            return '${' + literal(json.dumps(v, ensure_ascii=False)) + '}'
        if isinstance(value, bool):
            encode = lambda expr: '${' + expr + '?string?boolean?c}'
        elif isinstance(value, (int, float)):
            encode = lambda expr: '${' + expr + '?number?c}'
        else:
            encode = lambda expr: '"${' + expr + '?string?json_string}"'
        return conditional(path, encode, constant, value)

    if request.target.format.upper() == 'XML':
        root = xml_root(request.target.payload)
        marker = 'WORKBENCH'
        while marker in request.target.payload:
            marker += '_X'
        placeholders = {}
        def visit(node, path):
            plan = loops.get(path)
            if plan:
                token = f'{marker}_LOOP_{len(placeholders)}'
                placeholders[token+'_START'] = start_loop(plan)
                placeholders[token+'_END'] = '</#list>'
                node.addprevious(etree.Comment(token+'_START'))
                node.addnext(etree.Comment(token+'_END'))
            if len(node):
                counts, seen = Counter(child.tag for child in node), Counter()
                for child in list(node):
                    if not isinstance(child.tag, str):
                        continue
                    child_path = path + (child.tag,)
                    if counts[child.tag] > 1:
                        child_path += (seen[child.tag],)
                        if seen[child.tag] > 0 and path+(child.tag,0) in loops:
                            node.remove(child)
                            continue
                    seen[child.tag] += 1
                    visit(child, child_path)
            else:
                token = f'{marker}_VALUE_{len(placeholders)}'
                encode = lambda expr: '${' + expr + '?string?xml}'
                constant = lambda value: '' if value == '' else '${' + literal(value) + '?xml}'
                placeholders[token] = conditional(path, encode, constant, node.text or '') if path in mapped else constant(node.text or '')
                node.text = token
            if plan:
                active.pop()
        visit(root, (root.tag,))
        template = etree.tostring(root, encoding='unicode', pretty_print=True)
        # XML attributes remain constants; disallow interpolation in them.
        if '${' in template or '#{' in template:
            raise ValueError('Template expressions are not allowed in XML sample attributes.')
        # Single-pass replacement avoids VALUE_1 corrupting VALUE_10 into "...0".
        template = re.sub(rf'<!--({marker}_LOOP_\d+_(?:START|END))-->|({marker}_VALUE_\d+)',
                          lambda m: placeholders[m[1] or m[2]], template)
    elif request.target.format.upper() == 'ISO':
        encode = lambda expr: '${' + expr + '?string}'
        constant = lambda value: '${' + literal(value) + '}'
        template = '\n'.join(str(key) + '=' + (conditional((key,), encode, constant, value) if (key,) in mapped else constant(value)) for key, value in target.items())
        warnings.append('ISO output is a field-number=value demo representation, not packed ISO 8583 wire bytes.')
    else:
        template = render_json(target)
    preamble = PREAMBLE
    if request.source.format.upper() == 'XML':
        preamble = PREAMBLE.replace('JsonUtils.getJsonAsMap(input)', "xml['child::node()']")
    if request.direction.upper() == 'REQUEST':
        # Accept raw demo samples as well as the real gateway request envelope.
        preamble += setup(request.source.format.upper() == 'XML')
    return {'template': preamble + guards + '\n' + template, 'mappings': rows,
            'validations': rules, 'filters': request.filters, 'source_fields': [n for n,pair in sources.items() if not any(isinstance(p,int) and p>0 for p in pair[0])], 'target_fields': list(targets),
            'source_format': request.source.format, 'target_format': request.target.format,
            'direction': request.direction, 'warnings': warnings,
            'collections': [{'target':path_name(path), 'source':path_name(plan['source']), 'variable':plan['variable']} for path,plan in loops.items()],
            'confidence': round(sum(x['confidence'] for x in rows) / len(rows), 2),
            'runtime_input': source}
