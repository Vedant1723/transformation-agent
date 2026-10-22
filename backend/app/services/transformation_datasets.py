from app.core.observability import traced as _log_traced, exception_event as _log_exception
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.user import UserModel
from app.transformations.conversation_models import TransformationSession, TransformationDataset, TransformationDatasetPolicy
from app.transformations.dataset import candidates, build_manifest, digest
from app.transformations.dataset_policy import related, invalid_records



@_log_traced('app.services.transformation_datasets.reviewed', level=20)
def reviewed(db, user):
    return candidates(db.scalars(select(TransformationSession).where(
        TransformationSession.user_id == user.id).order_by(TransformationSession.id)).all())


@_log_traced('app.services.transformation_datasets.policy', level=20)
def policy(db, user, lock=False):
    if lock:
        db.scalar(select(UserModel).where(UserModel.id == user.id).with_for_update())
        db.scalars(select(TransformationSession).where(TransformationSession.user_id == user.id).with_for_update()).all()
    row = db.get(TransformationDatasetPolicy, user.id)
    return row.state if row else {'excluded': {}, 'benchmark_id': None}


@_log_traced('app.services.transformation_datasets.benchmark', level=20)
def benchmark(db, user, state):
    if not state.get('benchmark_id'):
        return []
    row = db.scalar(select(TransformationDataset).where(TransformationDataset.id == state['benchmark_id'], TransformationDataset.user_id == user.id))
    return [r for r in row.manifest['records'] if r['split'] == 'evaluation']


@_log_traced('app.services.transformation_datasets.historical_rows', level=20)
def historical_rows(db, user):
    versions = db.scalars(select(TransformationDataset).where(TransformationDataset.user_id == user.id)).all()
    return [{'key': f'history:{v.id}:{i}', 'session_id': r['provenance']['session_id'], 'lineage_sessions': r['provenance'].get('lineage_sessions', []), 'example': r['example']}
        for v in versions for i, r in enumerate(v.manifest['records'])]


@_log_traced('app.services.transformation_datasets.eligibility', level=20)
def eligibility(rows, state, seeds, history=()):
    reserved = related(list(rows) + list(history), seeds)
    for row in rows:
        row['excluded'] = str(row['session_id']) in state.get('excluded', {})
        row['reserved'] = row['key'] in reserved
        if row['excluded']:
            row['reasons'].append('Conversation explicitly excluded from datasets')
        if row['reserved']:
            row['reasons'].append('Reserved for fixed evaluation; cannot select for training')
        row['eligible'] = not row['reasons']
    return rows


@_log_traced('app.services.transformation_datasets.get_policy', level=20)
def get_policy(user: UserModel, db: Session):
    return {'success': True, 'data': policy(db, user)}


class Exclusion(BaseModel):
    excluded: bool


@_log_traced('app.services.transformation_datasets.exclude', level=20)
def exclude(session_id: int, request: Exclusion, user: UserModel, db: Session):
    state = dict(policy(db, user, lock=True))
    session = db.scalar(select(TransformationSession).where(TransformationSession.id == session_id, TransformationSession.user_id == user.id))
    if not session:
        raise HTTPException(404, 'Conversation not found.')
    excluded = dict(state.get('excluded', {}))
    if request.excluded:
        excluded[str(session_id)] = datetime.now(timezone.utc).isoformat()
    else:
        excluded.pop(str(session_id), None)
    state['excluded'] = excluded
    db.merge(TransformationDatasetPolicy(user_id=user.id, state=state)); db.commit()
    return {'success': True, 'data': state}


@_log_traced('app.services.transformation_datasets.freeze_benchmark', level=20)
def freeze_benchmark(version_id: int, user: UserModel, db: Session):
    state = dict(policy(db, user, lock=True))
    if state.get('benchmark_id'):
        raise HTTPException(409, 'A fixed benchmark already exists. It cannot be silently replaced.')
    versions = db.scalars(select(TransformationDataset).where(TransformationDataset.user_id == user.id)).all()
    version = next((r for r in versions if r.id == version_id), None)
    if not version:
        raise HTTPException(404, 'Dataset version not found.')
    seeds = [r for r in version.manifest['records'] if r['split'] == 'evaluation']
    rows = reviewed(db, user)
    if not seeds or invalid_records(seeds, rows, state.get('excluded', {})):
        raise HTTPException(422, 'Benchmark requires nonempty, currently approved evaluation records.')
    # Include historical records to detect even rejected/deleted-review bridge templates.
    historical = [r for v in versions for r in v.manifest['records']]
    historical_rows = [{'key': str(i), 'session_id': r['provenance']['session_id'], 'lineage_sessions': r['provenance'].get('lineage_sessions', []), 'example': r['example']} for i, r in enumerate(historical)]
    linked = related(historical_rows + rows, seeds)
    if any(str(i) in linked and r['split'] == 'train' for i, r in enumerate(historical)):
        raise HTTPException(409, 'Related examples were already exported for training. Use an independent evaluation dataset.')
    state['benchmark_id'] = version_id
    db.merge(TransformationDatasetPolicy(user_id=user.id, state=state)); db.commit()
    return {'success': True, 'data': state}


@_log_traced('app.services.transformation_datasets.list_candidates', level=20)
def list_candidates(user: UserModel, db: Session):
    # Metadata only: flagged material is not echoed in this screen.
    state = policy(db, user)
    rows = eligibility(reviewed(db, user), state, benchmark(db, user, state), historical_rows(db, user))
    return {'success': True, 'data': [{k: v for k, v in r.items() if k != 'example'} for r in rows]}


@_log_traced('app.services.transformation_datasets.ranker_readiness', level=20)
def ranker_readiness(user: UserModel, db: Session):
    """Read-only server-derived readiness; never trusts imported approval flags."""
    state = policy(db, user)
    current = reviewed(db, user)
    seeds = benchmark(db, user, state)
    benchmark_blocked = bool(seeds and invalid_records(seeds, current, state.get('excluded', {})))
    rows = eligibility(current, state, seeds, historical_rows(db, user))
    items = []
    for row in rows:
        reasons = list(row['reasons'])
        if benchmark_blocked:
            reasons.append('Fixed benchmark requires governance review')
        if not seeds:
            reasons.append('A fixed independent benchmark is required before model training')
        # Current reviewed-example schema has no authenticated partner/route binding.
        # Never infer this from a conversation title or arbitrary payload metadata.
        reasons.append('Reviewed example has no verified partner/route scope binding')
        items.append({'key': row['key'], 'fingerprint': row['fingerprint'],
                      'session_id': row['session_id'], 'dataset_eligible': row['eligible'],
                      'ranker_ready': False, 'reasons': reasons})
    return {'success': True, 'data': {'source': 'authenticated-application-reviews',
            'benchmark_id': state.get('benchmark_id'), 'benchmark_blocked': benchmark_blocked,
            'training_started': False, 'ready_count': 0, 'items': items,
            'limitations': ['Read-only readiness snapshot, not training authorization.',
                            'Partner/route scope must be stored and reviewed before ranker ingestion.']}}


class ExportSelection(BaseModel):
    fingerprints: dict[str, str] = Field(min_length=1, max_length=500)
    human_reviewed: bool = False


@_log_traced('app.services.transformation_datasets.export', level=20)
def export(request: ExportSelection, user: UserModel, db: Session):
    if not request.human_reviewed:
        raise HTTPException(422, 'Confirm human review of the selected examples before export.')
    state = policy(db, user, lock=True)
    rows = reviewed(db, user)
    seeds = benchmark(db, user, state)
    if seeds and invalid_records(seeds, rows, state.get('excluded', {})):
        raise HTTPException(409, 'Fixed benchmark has an excluded, changed or rejected review. Export blocked pending benchmark governance review.')
    if seeds:
        old_versions = db.scalars(select(TransformationDataset).where(TransformationDataset.user_id == user.id)).all()
        history = [r for v in old_versions for r in v.manifest['records']]
        history_candidates = [{'key': f'prior:{i}', 'session_id': r['provenance']['session_id'], 'lineage_sessions': r['provenance'].get('lineage_sessions', []), 'example': r['example']} for i, r in enumerate(history)]
        connected = related(rows + history_candidates, seeds)
        if any(f'prior:{i}' in connected and r['split'] == 'train' for i, r in enumerate(history)):
            raise HTTPException(409, 'New links connect the benchmark to previously exported training data. Export blocked for leakage review.')
    available = {r['key']: r for r in eligibility(rows, state, seeds, historical_rows(db, user))}
    selected = []
    for key, fingerprint in request.fingerprints.items():
        row = available.get(key)
        if not row or row['fingerprint'] != fingerprint:
            raise HTTPException(409, 'Reviews changed. Refresh the dataset and select examples again.')
        if not row['eligible']:
            raise HTTPException(422, 'An example is blocked. Correct synthetic data in a clean conversation, retest and approve it.')
        selected.append(row)
    manifest = build_manifest(sorted(selected, key=lambda r: r['key']))
    if seeds:
        for record in manifest['records']:
            record['split'] = 'train'
        manifest['records'] += seeds
        manifest['counts'] = {'train': len(selected), 'evaluation': len(seeds)}
        manifest['content_sha256'] = digest(manifest['records'])
        manifest['benchmark_id'] = state['benchmark_id']
        manifest['split_policy'] = 'Fixed evaluation snapshot; selected unrelated examples are training only'
        manifest['group_count'] = len({r['group'] for r in manifest['records']})
        manifest['warnings'] = []
        manifest['limitations'][2] = 'Evaluation is pinned to benchmark_id. Never train on any benchmark or reserved related example.'
    manifest['created_at'] = datetime.now(timezone.utc).isoformat()
    row = TransformationDataset(user_id=user.id, manifest=manifest)
    db.add(row); db.commit(); db.refresh(row)
    return {'success': True, 'data': {'id': row.id, 'manifest': row.manifest}}


@_log_traced('app.services.transformation_datasets.versions', level=20)
def versions(user: UserModel, db: Session):
    state = policy(db, user)
    current = reviewed(db, user)
    rows = db.scalars(select(TransformationDataset).where(TransformationDataset.user_id == user.id)
        .order_by(TransformationDataset.id.desc())).all()
    return {'success': True, 'data': [{'id': r.id, 'created_at': r.created_at.isoformat(),
        'counts': r.manifest['counts'], 'content_sha256': r.manifest['content_sha256'],
        'blocked': invalid_records(r.manifest['records'], current, state.get('excluded', {}))} for r in rows]}


@_log_traced('app.services.transformation_datasets.version', level=20)
def version(version_id: int, user: UserModel, db: Session):
    row = db.scalar(select(TransformationDataset).where(TransformationDataset.id == version_id,
        TransformationDataset.user_id == user.id))
    if not row:
        raise HTTPException(404, 'Dataset version not found.')
    if invalid_records(row.manifest['records'], reviewed(db, user), policy(db, user).get('excluded', {})):
        raise HTTPException(409, 'Download blocked: a contained example was excluded, changed or rejected. Previously downloaded files cannot be recalled.')
    return {'success': True, 'data': {'id': row.id, 'manifest': row.manifest}}
