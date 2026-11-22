from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select
from .database import Base, engine, get_db
from .models import Payment
from .schemas import PaymentCreate
from .services import create_payment, refund_payment, dashboard_stats

BASE = Path(__file__).resolve().parent.parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Payment Processing System", version="1.0.0", lifespan=lifespan)
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
def list_payments(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).order_by(Payment.id.desc()).limit(min(limit, 250))).all()
    return [payment_json(p) for p in rows]

@app.post("/api/payments", status_code=201)
def new_payment(payload: PaymentCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    try:
        payment, replayed = create_payment(db, payload, idempotency_key)
        return {**payment_json(payment), "idempotent_replay": replayed}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

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
        raise HTTPException(status_code=409, detail=str(exc))

def payment_json(p: Payment):
    return {
        "payment_id": p.payment_id, "customer_name": p.customer_name,
        "customer_email": p.customer_email, "amount": p.amount_paise / 100,
        "currency": p.currency, "method": p.method, "status": p.status,
        "description": p.description,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
