from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Literal

class PaymentCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: str = Field(min_length=5, max_length=180)
    amount: float = Field(gt=0, le=500000)
    currency: Literal["INR"] = "INR"
    method: Literal["Card", "UPI", "Wallet", "Net Banking"]
    description: str = Field(default="Online purchase", max_length=240)

class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    payment_id: str
    customer_name: str
    customer_email: str
    amount_paise: int
    currency: str
    method: str
    status: str
    description: str
    created_at: str | None = None
