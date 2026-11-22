from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PaymentCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    customer_email: EmailStr = Field(max_length=180)
    amount: Decimal = Field(
        gt=Decimal("0"), le=Decimal("500000"), max_digits=8, decimal_places=2
    )
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
