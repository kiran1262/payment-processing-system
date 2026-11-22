import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Payment
from .schemas import PaymentCreate
from .services import IdempotencyConflictError, create_payment, dashboard_stats, refund_payment

logger = logging.getLogger(__name__)
BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="Payment Processing System", version="1.1.0")
app.mount("/static", StaticFiles(directory=BASE / "frontend"), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(BASE / "frontend" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "Payment"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return dashboard_stats(db)


@app.get("/api/payments")
def list_payments(
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Payment).order_by(Payment.id.desc()).limit(limit)).all()
    return [payment_json(payment) for payment in rows]


@app.post("/api/payments", status_code=201)
def new_payment(
    payload: PaymentCreate,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=100
    ),
    db: Session = Depends(get_db),
):
    try:
        payment, replayed = create_payment(db, payload, idempotency_key)
        return {**payment_json(payment), "idempotent_replay": replayed}
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Database error while creating payment")
        raise HTTPException(status_code=500, detail="Payment could not be processed.") from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error while creating payment")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@app.get("/api/payments/{payment_id}")
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    payment = db.scalar(select(Payment).where(Payment.payment_id == payment_id))
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment_json(payment)


@app.post("/api/payments/{payment_id}/refund")
def refund(payment_id: str, db: Session = Depends(get_db)):
    payment = db.scalar(select(Payment).where(Payment.payment_id == payment_id))
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    try:
        return payment_json(refund_payment(db, payment))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Database error while refunding payment %s", payment_id)
        raise HTTPException(status_code=500, detail="Refund could not be processed.") from exc


def payment_json(payment: Payment):
    return {
        "payment_id": payment.payment_id,
        "customer_name": payment.customer_name,
        "customer_email": payment.customer_email,
        "amount": payment.amount_paise / 100,
        "currency": payment.currency,
        "method": payment.method,
        "status": payment.status,
        "description": payment.description,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
    }
