"""Conservative curation helpers. Heuristic scanning is not anonymization.

Conversation and identical-template links form connected split groups. Splits
are reproducible within a snapshot, not a permanent benchmark across versions.
"""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy
import hashlib
import json
import re


@_log_traced('app.transformations.dataset.digest', level=10)
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def scan(value):
    # Report categories only: never echo potentially sensitive matched text.
    findings = set()
    def strings(item):
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for key, child in item.items():
                yield str(key) + ':'
                yield from strings(child)
        elif isinstance(item, list):
            for child in item:
                yield from strings(child)
    text = json.dumps(value, ensure_ascii=False) + '\n' + '\n'.join(strings(value))
    patterns = {
        'credential-like key or assignment': r'(?i)(?:["\s<]|^)(?:password|passwd|secret|client_secret|api[_-]?key|authorization|cookie|token|access[_-]?token|refresh[_-]?token|pin)["\s>:=]',
        'bearer credential': r'(?i)\bbearer\s+[a-z0-9._~+/-]{8,}',
        'private key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'credential-bearing URL': r'://[^\s/:"<>]+:[^\s@"<>]+@',
        'email address': r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',
        'long number (possible phone/account)': r'(?<!\d)\d{10,19}(?!\d)',
    }
    for category, pattern in patterns.items():
        if re.search(pattern, text, re.I):
            findings.add(category)
    return sorted(findings)


@_log_traced('app.transformations.dataset.candidates', level=10)
def candidates(sessions):
    result = []
    for session in sessions:
        latest = {}
        for index, example in enumerate(session.state.get('examples', [])):
            latest[example['revision']] = (index, example)
        for revision, (index, example) in latest.items():
            reasons = []
            if example.get('status') != 'approved':
                reasons.append('Latest review is not approved')
            if not example.get('sanitized_attested'):
                reasons.append('Sanitization confirmation missing')
            if not (example.get('test') or {}).get('passed'):
                reasons.append('Passing baseline test missing')
            findings = scan(example)
            cases=example.get('validation_cases',[])
            results=example.get('case_results',[])
            if len(cases)!=len(results) or any(not result.get('passed') for result in results):
                reasons.append('Passing correction scenario evidence missing')
            if findings:
                reasons.append('Sensitive-data scan requires a clean, retested example')
            result.append({'key': f'{session.id}:{revision}:{index}', 'session_id': session.id,
                'lineage_sessions': session.state.get('lineage_sessions', []),
                'session_version': session.version, 'title': session.title, 'revision': revision,
                'status': example.get('status'), 'eligible': not reasons, 'reasons': reasons,
                'findings': findings, 'fingerprint': digest(example), 'example': copy.deepcopy(example)})
    return result


@_log_traced('app.transformations.dataset.build_manifest', level=10)
def build_manifest(rows):
    parents = list(range(len(rows)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    seen = {}
    for i, row in enumerate(rows):
        # Normalize whitespace only; semantic near-duplicates need human review.
        template = re.sub(r'\s+', ' ', row['example']['template']).strip()
        keys = [('session', sid) for sid in [row['session_id']] + row.get('lineage_sessions', [])]
        for key in keys + [('template', digest(template))]:
            if key in seen:
                parents[root(i)] = root(seen[key])
            seen[key] = i
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append(row['key'])
    records = []
    for i, row in enumerate(rows):
        group = digest(sorted(groups[root(i)]))
        records.append({'id': row['key'], 'group': group,
            'split': 'evaluation' if int(group[:8], 16) % 5 == 0 else 'train',
            'provenance': {**{k: row[k] for k in ('session_id', 'session_version', 'revision', 'fingerprint')},
                'lineage_sessions': row.get('lineage_sessions', [])},
            'example': row['example']})
    counts = {split: sum(r['split'] == split for r in records) for split in ('train', 'evaluation')}
    return {'schema_version': 1, 'purpose': 'Curated examples; no model training performed',
        'split_policy': 'conversation + whitespace-normalized identical-template connected groups; SHA256 group modulo 5 holdout',
        'limitations': ['Heuristic scan can miss sensitive data. Human review remains required.',
            'Related but nonidentical templates are not detected automatically.',
            'Split membership is frozen in this version only. Do not combine versions as an independent benchmark.',
            'Passing execution is not proof of correct business behavior. Scenario failures are observations.'],
        'counts': counts, 'group_count': len(groups),
        'warnings': [] if all(counts.values()) else ['One split is empty; collect more independent groups before training/evaluation.'],
        'records': records, 'content_sha256': digest(records)}
