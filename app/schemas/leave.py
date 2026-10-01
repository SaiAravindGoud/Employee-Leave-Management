from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class LeaveCreate(BaseModel):
    employee_id: int = Field(gt=0)
    leave_type: str
    start_date: date
    end_date: date
    reason: str = Field(min_length=2, max_length=500)


class LeaveReject(BaseModel):
    rejection_reason: str = Field(min_length=2, max_length=500)


class LeaveResponse(BaseModel):
    id: int
    employee_id: int
    leave_type: str
    start_date: date
    end_date: date
    total_days: Decimal
    reason: str
    status: str
    approved_by: int | None
    rejection_reason: str | None

    model_config = {"from_attributes": True}