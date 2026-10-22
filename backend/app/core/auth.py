"""Gateway-only identity dependency; no local login or token verification."""
from app.core.gateway_identity import gateway_user

get_current_user = gateway_user
