"""Conservative inspection and explicit edits; not an arbitrary FreeMarker compiler."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import difflib
import re

REFERENCE = re.compile(r'\b(?:body|input|xml)(?:(?:\.[A-Za-z_][\w]*)|(?:\[(?:\d+|"[^"\n]*"|\'[^\'\n]*\')\]))+')


def expressions(template):
    """Locate interpolation bodies respecting quoted braces and nested literals."""
    index = 0
    while index < len(template):
        if template.startswith('<#--', index):
            end = template.find('-->', index + 4)
            index = len(template) if end < 0 else end + 3
            continue
        if not template.startswith('${', index):
            index += 1
            continue
        start, cursor, depth, quote = index, index + 2, 1, None
        while cursor < len(template):
            char = template[cursor]
            if quote:
                if char == '\\':
                    cursor += 2
                    continue
                if char == quote:
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if not depth:
                    yield start, cursor + 1, template[start + 2:cursor]
                    break
            cursor += 1
        else:
            raise ValueError(f'Unclosed interpolation at line {template.count(chr(10), 0, start) + 1}.')
        index = cursor + 1


@_log_traced('app.transformations.template_tools.inspect', level=10)
def inspect(template):
    clean = re.sub(r'<#--[\s\S]*?-->', lambda m: '\n' * m[0].count('\n'), template)
    references = sorted(set(REFERENCE.findall(clean)))
    mappings = []
    for start, end, expr in expressions(template):
        prefix = template[:start]
        # Target labels are lexical hints only; directives/macros can change output structure.
        xml = re.search(r'<([A-Za-z_][\w:.-]*)[^<>]*>[^<>]*$', prefix)
        js = re.search(r'"([^"\n]+)"\s*:\s*"?$', prefix)
        target = xml[1] if xml else js[1] if js else '(conditional / computed context)'
        mappings.append({'line':template.count('\n', 0, start)+1,'target':target,
                         'expression':expr,'sources':sorted(set(REFERENCE.findall(expr)))})
    return {'mappings':mappings, 'source_references':references,
        'directives': {name: len(re.findall(r'<#'+name+r'\b', clean)) for name in ('if','elseif','list','assign','macro','function','stop','include','import')},
        'warnings': ['Static inspection is best-effort, not compilation or proof of correctness. Target labels may be approximate inside conditions, loops, macros or dynamic keys. Render with representative inputs to verify.',
                     'External includes, imports and organisation-specific helpers require the same dependencies in this local runtime.']}


@_log_traced('app.transformations.template_tools.compare', level=10)
def compare(before, after):
    left, right = inspect(before), inspect(after)
    diff = '\n'.join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile='Original', tofile='Proposed', lineterm=''))
    if before != after and not diff:
        diff = 'Only line endings or the final newline differ.'
    return {'identical':before == after,
        'diff':diff,
        'added_sources':sorted(set(right['source_references']) - set(left['source_references'])),
        'removed_sources':sorted(set(left['source_references']) - set(right['source_references'])),
        'before':left, 'after':right}


@_log_traced('app.transformations.template_tools.revise', level=10)
def revise(template, instructions, replacements):
    edits = list(replacements)
    for line in instructions.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(?:replace|change)\s+(.+?)\s+(?:with|to)\s+(.+?)\s*', line, re.I)
        if not match:
            raise ValueError('No changes applied. Supported instruction: replace OLD with NEW (one per line). For other requirements, use the exact replacement fields or edit the template directly and render it.')
        edits.append({'find':match[1], 'replace':match[2]})
    if not edits:
        raise ValueError('Describe a replacement or fill the exact replacement fields.')
    result, changes = template, []
    for edit in edits:
        old, new = edit.get('find', ''), edit.get('replace', '')
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ValueError('Replacement text must be strings and Find must not be empty.')
        count = result.count(old)
        if not count:
            raise ValueError(f'No changes applied: exact text {old!r} was not found.')
        result = result.replace(old, new)
        if len(result) > 50000:
            raise ValueError('Proposed template exceeds 50,000 characters.')
        changes.append({'find':old,'replace':new,'occurrences':count})
    return {'template':result,'changes':changes, **compare(template,result)}
