from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from uuid import uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Payment

logger = logging.getLogger(__name__)
PAYMENT_METHODS = ("Card", "UPI", "Wallet", "Net Banking")


class IdempotencyConflictError(ValueError):
    """Raised when a key is reused for a different payment request."""


def _matches_request(payment: Payment, payload) -> bool:
    return (
        payment.customer_name == payload.customer_name
        and payment.customer_email == str(payload.customer_email)
        and payment.amount_paise == int(payload.amount * 100)
        and payment.currency == payload.currency
        and payment.method == payload.method
        and payment.description == payload.description
    )


def create_payment(db: Session, payload, idempotency_key: str | None):
    if idempotency_key:
        existing = db.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if existing:
            if not _matches_request(existing, payload):
                raise IdempotencyConflictError(
                    "This Idempotency-Key was already used with a different request."
                )
            return existing, True

    amount_paise = int(payload.amount * 100)
    status = "declined" if amount_paise % 100 == 99 else "succeeded"
    payment = Payment(
        payment_id=f"pay_{uuid4().hex[:14]}",
        customer_name=payload.customer_name,
        customer_email=str(payload.customer_email),
        amount_paise=amount_paise,
        currency=payload.currency,
        method=payload.method,
        status=status,
        description=payload.description,
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # Another request may have inserted the unique key after our initial read.
        db.rollback()
        if not idempotency_key:
            raise
        existing = db.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        if not _matches_request(existing, payload):
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used with a different request."
            )
        return existing, True

    db.refresh(payment)
    return payment, False


def refund_payment(db: Session, payment: Payment):
    # Conditional UPDATE makes the succeeded -> refunded transition atomic.
    result = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == "succeeded")
        .values(status="refunded", refunded_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        db.rollback()
        db.refresh(payment)
        if payment.status == "refunded":
            return payment
        raise ValueError("Only successful payments can be refunded")

    db.commit()
    db.refresh(payment)
    return payment


def dashboard_stats(db: Session):
    total = func.count(Payment.id)
    succeeded = func.sum(case((Payment.status == "succeeded", 1), else_=0))
    refunded = func.sum(case((Payment.status == "refunded", 1), else_=0))
    declined = func.sum(case((Payment.status == "declined", 1), else_=0))
    successful_outcomes = func.sum(
        case((Payment.status.in_(("succeeded", "refunded")), 1), else_=0)
    )
    revenue = func.coalesce(
        func.sum(case((Payment.status == "succeeded", Payment.amount_paise), else_=0)),
        0,
    )
    row = db.execute(
        select(
            total.label("total"),
            succeeded.label("succeeded"),
            refunded.label("refunded"),
            declined.label("declined"),
            successful_outcomes.label("successful_outcomes"),
            revenue.label("revenue"),
        )
    ).one()

    method_rows = db.execute(
        select(Payment.method, func.count(Payment.id)).group_by(Payment.method)
    ).all()
    methods = {method: 0 for method in PAYMENT_METHODS}
    methods.update({method: count for method, count in method_rows})
    total_count = row.total or 0

    return {
        "total_transactions": total_count,
        "successful": row.succeeded or 0,
        "failed": row.declined or 0,
        "refunded": row.refunded or 0,
        "revenue_paise": row.revenue or 0,
        "success_rate": round((row.successful_outcomes or 0) / total_count * 100, 1)
        if total_count else 0,
        "methods": methods,
    }
