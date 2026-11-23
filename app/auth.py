from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
import hmac
import secrets
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import AuthSession, Tenant, User, utcnow

SESSION_LIFETIME = timedelta(hours=12)
PASSWORD_ITERATIONS = 310_000
bearer_scheme = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256\u0024{PASSWORD_ITERATIONS}\u0024{salt.hex()}\u0024{digest.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()

def issue_session(db: Session, user: User):
    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + SESSION_LIFETIME
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires_at))
    db.commit()
    return token, expires_at

def create_tenant_owner(db: Session, tenant_name: str, full_name: str, email: str, password: str):
    tenant = Tenant(name=tenant_name.strip())
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, full_name=full_name.strip(), email=email.lower(),
                password_hash=hash_password(password), role="owner")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)
    token, expires_at = issue_session(db, user)
    return tenant, user, token, expires_at

def bootstrap_legacy_owner(db: Session, full_name: str, email: str, password: str) -> User:
    """Create the first owner of the migration-created legacy workspace.

    This is deliberately a local administrative operation, never an HTTP endpoint.
    It refuses to proceed if the expected workspace is absent or already has users.
    """
    tenant = db.get(Tenant, 1)
    if tenant is None or tenant.name != "Legacy demo workspace":
        raise ValueError("The Legacy demo workspace was not found; verify migration 0002.")
    existing_user = db.scalar(select(User).where(User.tenant_id == tenant.id).limit(1))
    if existing_user is not None:
        raise ValueError("The legacy workspace already has an account; bootstrap is one-time only.")
    normalized_email = email.strip().lower()
    if not normalized_email or not full_name.strip() or not password:
        raise ValueError("Name, email, and password are required.")
    user = User(
        tenant_id=tenant.id,
        full_name=full_name.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
        role="owner",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(user)
    return user

def _utc(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
                     db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(credentials.credentials)))
    if session is None or session.revoked_at is not None or _utc(session.expires_at) <= utcnow():
        raise unauthorized
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user

def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(403, "Owner permission required")
    return user
