"""Request-only metadata, kept separate from the basic payload and XML DOM."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re

CONTEXT_MARKER = '<#-- control-room request context -->'


@_log_traced('app.transformations.request_context.setup', level=10)
def setup(xml=False):
    missing = '!(body.request)?has_content' if xml else '!(body.request)?? || !body.request?is_hash'
    wrap = '{"request": body}' if xml else 'body + {"request": body}'
    merge = '{"request": body.request, ' if xml else 'body + {'
    return (CONTEXT_MARKER + '\n<#if ' + missing + '><#assign body = ' + wrap + '></#if>\n'
        '<#assign body = ' + merge + '"addProps": additionalProperties!(body.addProps!{}), "headers": headers!(body.headers!(body.header!{})), "header": headers!(body.headers!(body.header!{}))}>\n')


@_log_traced('app.transformations.request_context.runtime_template', level=10)
def runtime_template(template, direction):
    if direction != 'REQUEST' or CONTEXT_MARKER in template:
        return template
    # Only known body initializers; never rewrite arbitrary assignments or field expressions.
    pattern = r'<#assign\s+body\s*=\s*(JsonUtils\.getJsonAsMap\(input\)|xml\[\s*[\'\"]child::node\(\)[\'\"]\s*\])\s*>'
    return re.sub(pattern, lambda m: m[0] + '\n' + setup(m[1].startswith('xml')), template)
