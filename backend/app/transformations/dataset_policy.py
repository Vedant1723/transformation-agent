"""Exact-template/conversation isolation; not semantic near-duplicate detection."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re
from app.transformations.dataset import digest


@_log_traced('app.transformations.dataset_policy.template_key', level=10)
def template_key(example):
    return digest(re.sub(r'\s+', ' ', example['template']).strip())


@_log_traced('app.transformations.dataset_policy.related', level=10)
def related(rows, seeds):
    sessions = {sid for r in seeds for sid in [r['provenance']['session_id']] + r['provenance'].get('lineage_sessions', [])}
    templates = {template_key(r['example']) for r in seeds}
    found = set()
    changed = True
    while changed:
        changed = False
        for row in rows:
            relatives = set([row['session_id']] + row.get('lineage_sessions', []))
            if row['key'] not in found and (relatives & sessions or template_key(row['example']) in templates):
                found.add(row['key']); sessions.update(relatives); templates.add(template_key(row['example']))
                changed = True
    return found


@_log_traced('app.transformations.dataset_policy.invalid_records', level=10)
def invalid_records(records, rows, excluded):
    latest = {(r['session_id'], r['revision']): r for r in rows}
    for record in records:
        p = record['provenance']
        row = latest.get((p['session_id'], p['revision']))
        if str(p['session_id']) in excluded or not row or not row['eligible'] or row['fingerprint'] != p['fingerprint']:
            return True
    return False
