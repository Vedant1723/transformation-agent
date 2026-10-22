"""Provision an existing gateway subject locally; creates no usable password."""
import argparse
from sqlalchemy import select
from app.database.session import SessionLocal
from app.models.user import UserModel


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject',required=True)
    parser.add_argument('--email',required=True)
    args=parser.parse_args()
    if not 1<=len(args.subject)<=100 or args.subject!=args.subject.strip():parser.error('Subject must be 1–100 characters without surrounding whitespace.')
    if not 5<=len(args.email)<=255 or '@' not in args.email:parser.error('Provide a valid provisioning email.')
    with SessionLocal() as db:
        row=db.scalar(select(UserModel).where(UserModel.username==args.subject))
        if row is not None:
            print(f'Already provisioned: user_id={row.id}; no changes made.')
            return
        row=UserModel(username=args.subject,email=args.email,password_hash='!gateway-only-no-password',is_active=True)
        db.add(row)
        try:db.commit();db.refresh(row)
        except Exception:
            db.rollback()
            raise SystemExit('Provisioning failed. Verify migrations, connectivity and unique email; no credentials logged.') from None
        print(f'Provisioned user_id={row.id}. No login password or token created.')


if __name__=='__main__':main()
