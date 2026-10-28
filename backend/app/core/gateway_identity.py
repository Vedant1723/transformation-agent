"""Trusted gateway bridge; not an end-user login or token issuer."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import os
import secrets
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.user import UserModel


@_log_traced('app.core.gateway_identity.gateway_user', level=10)
def gateway_user(request: Request, db: Session = Depends(get_db)):
    if os.getenv('AUTH_MODE', 'gateway') == 'ingress':
        # Trusted proxy mode: ingress overwrites these metadata headers and
        # network controls must prevent direct backend access. Not credentials.
        for header, setting in (('x-channel-name', 'INGRESS_CHANNEL_NAME'),
                                ('x-service-id', 'INGRESS_SERVICE_ID')):
            expected = os.getenv(setting, '')
            if not expected:
                raise HTTPException(503, 'Ingress integration is not configured.')
            values = request.headers.getlist(header)
            if len(values) != 1 or values[0] != expected:
                raise HTTPException(403, 'Expected ingress metadata required.')
        subject = os.getenv('INGRESS_SHARED_SUBJECT', '')
        if not subject:
            raise HTTPException(503, 'Ingress shared identity is not configured.')
        user = db.scalar(select(UserModel).where(UserModel.username==subject, UserModel.is_active.is_(True)))
        if user is None:
            raise HTTPException(403, 'Shared service identity is not provisioned or is inactive.')
        return user
    secret = os.getenv('GATEWAY_SHARED_SECRET','')
    if len(secret.encode()) < 32:
        raise HTTPException(503,'Gateway integration is not configured.')
    supplied = request.headers.get('X-Gateway-Key','')
    if not secrets.compare_digest(supplied.encode(),secret.encode()):
        raise HTTPException(401,'Trusted gateway required.')
    subject = request.headers.get('X-Authenticated-User','')
    if not subject or len(subject)>100 or subject != subject.strip():
        raise HTTPException(401,'Verified gateway identity required.')
    user = db.scalar(select(UserModel).where(UserModel.username==subject,UserModel.is_active.is_(True)))
    if user is None:
        raise HTTPException(403,'Gateway identity is not provisioned or is inactive.')
    return user
