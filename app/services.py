from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from .models import Payment

def create_payment(db: Session, payload, idempotency_key: str | None):
    if idempotency_key:
        existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing:
            return existing, True
    # Demo-only deterministic decline: amounts ending in .99 simulate a decline.
    amount_paise = round(payload.amount * 100)
    status = "declined" if amount_paise % 100 == 99 else "succeeded"
    payment = Payment(
        payment_id=f"pay_{uuid4().hex[:14]}",
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        amount_paise=amount_paise,
        currency=payload.currency,
        method=payload.method,
        status=status,
        description=payload.description,
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment, False

def refund_payment(db: Session, payment: Payment):
    if payment.status == "refunded":
        return payment
    if payment.status != "succeeded":
        raise ValueError("Only successful payments can be refunded")
    payment.status = "refunded"
    payment.refunded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(payment)
    return payment

def dashboard_stats(db: Session):
    rows = db.scalars(select(Payment)).all()
    successful = [p for p in rows if p.status == "succeeded"]
    refunded = [p for p in rows if p.status == "refunded"]
    return {
        "total_transactions": len(rows),
        "successful": len(successful),
        "failed": sum(p.status == "declined" for p in rows),
        "refunded": len(refunded),
        "revenue_paise": sum(p.amount_paise for p in successful),
        "success_rate": round((len(successful) + len(refunded)) / len(rows) * 100, 1) if rows else 0,
        "methods": {m: sum(p.method == m for p in rows) for m in ["Card", "UPI", "Wallet", "Net Banking"]},
    }
