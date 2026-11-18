"""Small, reported syntax corrections; never repair business mappings implicitly."""
import re
from app.transformations.template_tools import expressions


def correct_bare_references(template):
    """Wrap bare output references, preserving FTL code and literal blocks."""
    protected=[]
    try:
        protected=[(start,end) for start,end,_ in expressions(template)]
    except ValueError:
        # Leave malformed interpolation syntax for the actual execution service.
        return template, []
    for match in re.finditer(r'<#--[\s\S]*?-->|<#noparse\b[^>]*>[\s\S]*?</#noparse\s*>',template):
        protected.append(match.span())
    # Quoted strings inside directives may themselves contain angle brackets.
    tag=re.compile(r'''</?[#@](?:[^>"']|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')*>''')
    tokens=[]
    for match in tag.finditer(template):
        if any(start<=match.start()<end for start,end in protected):continue
        tokens.append(match)
        protected.append(match.span())
    scopes=[]; changes=[]; cursor=0
    path=r'''(?:(?:\.[A-Za-z_]\w*)|(?:\[(?:\d+|"[^"\n]*"|'[^'\n]*')\]))*'''
    def output(start,end):
        names={'body'} | {name for name in scopes if name}
        pattern=re.compile(r'(?<![\w$\\])\$('+'|'.join(re.escape(n) for n in sorted(names))+r')(?!\w)'+path)
        for match in pattern.finditer(template,start,end):
            if any(a<=match.start()<b for a,b in protected):continue
            # Avoid rewriting only a prefix of a more complex expression.
            if match.end()<len(template) and template[match.end()] in '.?[!(' :continue
            if match[0]=='$body':continue
            changes.append({'line':template.count('\n',0,match.start())+1,
                'before':match[0], 'after':'${'+match[0][1:]+'}',
                'start':match.start(), 'end':match.end()})
    for token in tokens:
        output(cursor,token.start())
        if token[0].startswith('<#list'):
            alias=re.search(r'\bas\s+(\w+)\s*>$',token[0])
            scopes.append(alias[1] if alias else None)
        elif token[0].startswith('</#list') and scopes:scopes.pop()
        cursor=token.end()
    output(cursor,len(template))
    corrected=template
    for change in reversed(changes):
        corrected=corrected[:change['start']]+change['after']+corrected[change['end']:]
    return corrected,changes
