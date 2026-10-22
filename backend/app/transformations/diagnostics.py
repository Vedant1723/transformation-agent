"""Evidence-based, opt-in repairs. Never silently default missing business fields."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re
from difflib import SequenceMatcher
from app.transformations.workbench import normalize, leaves, expression
from app.transformations.structure import ALIASES

from app.transformations.template_tools import expressions


@_log_traced('app.transformations.diagnostics.suggest', level=10)
def suggest(template, payload, source_format, target_format, error='', direction='RESPONSE', properties=None, headers=None):
    suggestions = []
    try:
        fields = {expression(path,source_format,direction): value for path,value in leaves(normalize(payload, source_format))}
        if direction == 'REQUEST':
            fields.update({expression(path,'JSON','REQUEST'):value for path,value in leaves({'addProps':properties or {},'header':headers or {}})})
    except Exception:
        _log_exception('app.transformations.diagnostics:16', handled=True)
        fields = {}
    clean = re.sub(r'<#--[\s\S]*?-->', lambda m:' ' * len(m[0]), template)

    def add(title, reason, start, end, replacement, category='format', confidence='high'):
        suggestions.append({'id': str(len(suggestions)), 'title': title, 'reason': reason,
            'category':category, 'confidence':confidence,
            'start': start, 'end': end, 'before': template[start:end], 'after': replacement,
            'line': template.count('\n', 0, start) + 1})

    if target_format == 'JSON':
        # Only an unconditional, unnested list body: filters change separator semantics.
        for loop in re.finditer(r'<#list\b[^>]*>([\s\S]*?)</#list>',clean):
            content=loop[1]
            if re.search(r'<#(?:if|elseif|list|continue|break|sep)\b',content):
                continue
            comma=re.search(r',(?=\s*$)',content)
            if comma:
                offset=loop.start(1)+comma.start()
                add('Separate JSON list items without a trailing comma', 'This unconditional list emits a comma after its final item. <#sep> emits it only between iterations. Retest with empty, one-item and multi-item lists.',
                    offset,offset+1,'<#sep>,</#sep>','collection','review')

    # Only replace the initializer; changing all paths would require business intent.
    if source_format == 'XML':
        for match in re.finditer(r'<#assign\s+body\s*=\s*JsonUtils\.getJsonAsMap\(input\)\s*>', clean):
            add('Use the native XML model', 'XML uses xml[\'child::node()\']. Review root-relative paths after this change.',
                match.start(), match.end(), '<#assign body = xml[\'child::node()\']>')
    else:
        for match in re.finditer(r'<#assign\s+body\s*=\s*xml\[\s*[\'\"]child::node\(\)[\'\"]\s*\]\s*>', clean):
            add('Use the map input model', 'JSON and ISO field maps use JsonUtils, not the XML document model.',
                match.start(), match.end(), '<#assign body = JsonUtils.getJsonAsMap(input)>', 'initialization')
    if 'body' in error and re.search(r'\bbody\b', clean) and not re.search(r'<#(?:assign|local|global)\s+body\b', clean) and direction != 'REQUEST':
        init = "xml['child::node()']" if source_format == 'XML' else 'JsonUtils.getJsonAsMap(input)'
        header = re.match(r'\s*<#ftl\b[^>]*>',clean)
        position = header.end() if header else 0
        add('Initialize body', 'No body initializer was found. Review if your production environment supplies body externally.', position, position,
            '<#assign body = ' + init + '>\n', 'initialization','review')
    try:
        spans = list(expressions(template))
    except ValueError:
        _log_exception('app.transformations.diagnostics:55', handled=True)
        return suggestions
    for start, end, expr in spans:
        # Only simple field expressions: avoid rewriting macros, strings or complex logic.
        match = re.fullmatch(r'\s*(body(?:\.[A-Za-z_]\w*|\[(?:\d+|"[^"\n]+"|\'[^\'\n]+\')\])+)((?:\?(?:string|number|c|xml|json_string|trim))*)\s*',expr)
        if not match:
            continue
        reference, suffix = match.groups()
        if error and reference not in fields:
            leaf = re.findall(r'[A-Za-z_]\w*', reference)[-1].lower()
            def score(path):
                other=re.findall(r'[A-Za-z_]\w*',path)[-1].lower()
                return 1.0 if other in ALIASES.get(leaf,{leaf}) else SequenceMatcher(None,leaf,other).ratio()
            scored = sorted(((score(p),p) for p in fields),key=lambda x:(-x[0],x[1]))
            exact = [p for score,p in scored if score==1]
            candidates = exact if len(exact)==1 else [] if exact else [p for score,p in scored[:3] if score>=.8]
            for candidate in candidates:
                add('Review input field path', f'{reference} was not found at this path in the sample; {candidate} exists. Confirm its business meaning. No missing-field default is added.',
                    start, end, '${' + candidate + suffix + '}', 'mapping','review')
        wanted = 'xml' if target_format == 'XML' else 'json_string' if target_format == 'JSON' else None
        wrong = 'json_string' if wanted == 'xml' else 'xml'
        autoescape = bool(re.search(r'<#(?:ftl\b[^>]*output_format|outputformat\b|autoesc\b)',clean))
        quoted_json = target_format=='JSON' and bool(re.search(r'"[^"\n]*$',template[:start])) and template[end:end+1]=='"'
        if wanted and ('?' + wrong) in suffix and not autoescape and (wanted=='xml' or quoted_json):
            add('Match escaping to output format', 'Use output-specific escaping. Review the proposed expression before applying.',
                start, end, '${' + reference + suffix.replace('?' + wrong, '?' + wanted) + '}')
        elif wanted == 'xml' and '?xml' not in suffix and not autoescape:
            add('Escape XML text', 'Special characters such as & and < must be escaped in XML text. Do not use for intentional markup.',
                start, end, '${' + expr + ('?string' if '?string' not in suffix else '') + '?xml}')
        elif quoted_json and '?json_string' not in suffix and '?xml' not in suffix:
            add('Escape JSON string content', 'Quotes, backslashes and control characters require JSON string escaping.',
                start,end,'${'+expr+('?string' if '?string' not in suffix else '')+'?json_string}')
        if target_format=='JSON' and not quoted_json and isinstance(fields.get(reference),(int,float,bool)) and not suffix:
            add('Use JSON number/boolean formatting','Use ?c for locale-independent JSON scalar output.',start,end,'${'+reference+'?c}')
        if error and target_format=='JSON' and not quoted_json and isinstance(fields.get(reference),str) and not suffix and re.search(r'[:\[,]\s*$',template[:start]) and re.match(r'\s*[,}\]]',template[end:]):
            add('Render this value as a JSON string', 'The sample is text in an unquoted JSON value position. Choose this only if the partner expects a string; numeric targets need explicit conversion and validation instead.',
                start,end,'"${'+reference+'?json_string}"','type','review')
    return suggestions


@_log_traced('app.transformations.diagnostics.findings', level=10)
def findings(template, error, stage):
    rows = []
    def add(category,message):
        rows.append({'category':category,'message':message})
    clean=re.sub(r'<#--[\s\S]*?-->', '', template)
    if error:
        add(stage,error)
    if '[0]' in clean and '<#list' not in clean:
        add('collection','Index 0 without a list directive may omit later items. Define the intended repeating output block or regenerate with a collection target shape before changing it to a loop.')
    if re.search(r',\s*</#list>',clean):
        add('collection','A comma before </#list> may create trailing JSON commas. Use <#sep>,</#sep> between emitted items, accounting for filtered/skipped rows.')
    if any(word in error.lower() for word in ('missing','null')):
        add('missing-field','Check full paths and request direction. Define optional-field fallback explicitly; do not remove required-field validations just to make rendering pass.')
    if any(word in error.lower() for word in ('number','numeric','boolean')):
        add('type','Check sample types. Use ?number only for valid numeric text and ?c for JSON numbers/booleans. Invalid values need validation or an explicit business fallback.')
    if '<#include' in clean or '<#import' in clean:
        add('dependency','Includes/imports require the same named templates and helper dependencies as your organisation runtime.')
    return rows
