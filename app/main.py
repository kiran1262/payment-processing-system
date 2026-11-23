import logging
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import (
    bearer_scheme, create_tenant_owner, get_current_user, hash_password,
    issue_session, require_owner, token_digest, verify_password,
)
from .database import get_db
from .models import AuthSession, Payment, Tenant, User
from .schemas import LoginRequest, MemberCreate, PaymentCreate, RegisterRequest
from .services import IdempotencyConflictError, create_payment, dashboard_stats, refund_payment
from .rate_limit import enforce_rate_limit, rate_limit_ip, rate_limit_user
from .proxy import resolve_forwarded_client_ip
from .config import TRUSTED_PROXY_NETWORKS

logger = logging.getLogger(__name__)
BASE = Path(__file__).resolve().parent.parent
app = FastAPI(title="Payment Processing System", version="1.2.0")
app.mount("/static", StaticFiles(directory=BASE / "frontend"), name="static")


@app.middleware("http")
async def trusted_proxy_middleware(request, call_next):
    """Honor X-Forwarded-For only when the immediate peer is explicitly trusted."""
    peer = request.client
    if peer is not None and TRUSTED_PROXY_NETWORKS:
        forwarded_for = request.headers.get("x-forwarded-for")
        resolved = resolve_forwarded_client_ip(
            peer.host, forwarded_for, TRUSTED_PROXY_NETWORKS
        )
        if resolved != peer.host:
            request.scope["client"] = (resolved, peer.port)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(BASE / "frontend" / "index.html")


@app.get("/api/health")
def health():
    """Liveness only: confirms that the process can answer HTTP."""
    return {"status": "healthy", "probe": "liveness", "service": "Payment demo"}


@app.get("/api/ready")
def readiness(db: Session = Depends(get_db)):
    """Readiness: confirms the configured database can answer a simple query."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Readiness check failed: database unavailable")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready", "database": "available"}


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_ip("register")),
):
    try:
        tenant, user, token, expires_at = create_tenant_owner(
            db, payload.tenant_name, payload.full_name, str(payload.email), payload.password
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    return {
        "access_token": token, "token_type": "bearer", "expires_at": expires_at.isoformat(),
        "tenant": {"id": tenant.id, "name": tenant.name}, "user": user_json(user, db),
    }


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_ip("login")),
):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    token, expires_at = issue_session(db, user)
    return {
        "access_token": token, "token_type": "bearer", "expires_at": expires_at.isoformat(),
        "tenant": {"id": user.tenant_id}, "user": user_json(user, db),
    }


@app.get("/api/auth/me")
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("read")),
):
    return user_json(user, db)


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == token_digest(credentials.credentials),
        AuthSession.user_id == user.id,
    ))
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/tenant/members", status_code=status.HTTP_201_CREATED)
def create_member(
    payload: MemberCreate,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("member_create")),
):
    member = User(
        tenant_id=owner.tenant_id, full_name=payload.full_name.strip(),
        email=str(payload.email).lower(), password_hash=hash_password(payload.password),
        role="member",
    )
    db.add(member)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    db.refresh(member)
    return user_json(member, db)


@app.get("/api/dashboard")
def dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("read")),
):
    return dashboard_stats(db, user.tenant_id)


@app.get("/api/payments")
def list_payments(
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("read")),
):
    rows = db.scalars(select(Payment).where(Payment.tenant_id == user.tenant_id)
        .order_by(Payment.id.desc()).limit(limit)).all()
    return [payment_json(payment) for payment in rows]


@app.post("/api/payments", status_code=201)
def new_payment(
    payload: PaymentCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("payment_create")),
):
    try:
        payment, replayed = create_payment(db, payload, idempotency_key, user.tenant_id)
        return {**payment_json(payment), "idempotent_replay": replayed}
    except IdempotencyConflictError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Database error while creating payment")
        raise HTTPException(500, detail="Payment could not be processed.") from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error while creating payment")
        raise HTTPException(500, detail="An internal error occurred.") from exc


@app.get("/api/payments/{payment_id}")
def get_payment(
    payment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("read")),
):
    payment = db.scalar(select(Payment).where(
        Payment.payment_id == payment_id, Payment.tenant_id == user.tenant_id
    ))
    if payment is None:
        raise HTTPException(404, detail="Payment not found")
    return payment_json(payment)


@app.post("/api/payments/{payment_id}/refund")
def refund(
    payment_id: str,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_user("refund")),
):
    payment = db.scalar(select(Payment).where(
        Payment.payment_id == payment_id, Payment.tenant_id == owner.tenant_id
    ))
    if payment is None:
        raise HTTPException(404, detail="Payment not found")
    try:
        return payment_json(refund_payment(db, payment, owner.tenant_id))
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Database error while refunding payment %s", payment_id)
        raise HTTPException(500, detail="Refund could not be processed.") from exc


def user_json(user: User, db: Session | None = None):
    tenant = db.get(Tenant, user.tenant_id) if db is not None else None
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant.name if tenant is not None else None,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
    }


def payment_json(payment: Payment):
    return {
        "payment_id": payment.payment_id, "customer_name": payment.customer_name,
        "customer_email": payment.customer_email, "amount": payment.amount_paise / 100,
        "currency": payment.currency, "method": payment.method, "status": payment.status,
        "description": payment.description,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
    }
