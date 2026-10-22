"""Pin already-reviewed independent examples as an owner's evaluation benchmark."""
import argparse
from sqlalchemy import select
from app.database.session import SessionLocal
from app.models.user import UserModel
from app.transformations.conversation_models import TransformationDataset
from app.transformations.dataset import build_manifest, digest
from app.services import transformation_datasets as datasets
from app.services.transformation_jobs import operator


def configure(db, user, session_id):
    operator(user)
    if datasets.policy(db, user).get('benchmark_id'):
        raise ValueError('A benchmark is already configured; it cannot be replaced here.')
    rows = [r for r in datasets.reviewed(db, user) if r['session_id'] == session_id and r['eligible']]
    if not rows:
        raise ValueError('Choose a currently approved, sanitized independent correction session.')
    manifest = build_manifest(rows)
    for record in manifest['records']:
        record['split'] = 'evaluation'
    manifest['counts'] = {'train': 0, 'evaluation': len(rows)}
    manifest['content_sha256'] = digest(manifest['records'])
    row = TransformationDataset(user_id=user.id, manifest=manifest)
    db.add(row)
    db.commit()
    db.refresh(row)
    return datasets.freeze_benchmark(row.id, user, db)['data']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject', required=True)
    parser.add_argument('--benchmark-session-id', type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(UserModel).where(UserModel.username == args.subject, UserModel.is_active.is_(True)))
        if user is None: raise SystemExit('Active provisioned identity not found.')
        result = configure(db, user, args.benchmark_session_id)
        print('Evaluation benchmark configured:', result['benchmark_id'])


if __name__ == '__main__':
    main()
