from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.user import User
from app.schemas.leave import LeaveCreate, LeaveReject, LeaveResponse


router = APIRouter(
    prefix="/leaves",
    tags=["Leave Requests"],
)


ALLOWED_LEAVE_TYPES = {
    "Sick": 12,
    "Casual": 10,
    "Earned": 15,
}


def calculate_weekdays(start_date: date, end_date: date) -> int:
    total_days = 0
    current_date = start_date

    while current_date <= end_date:
        if current_date.weekday() < 5:
            total_days += 1
        current_date += timedelta(days=1)

    return total_days


def validate_leave_type(leave_type: str):
    if leave_type not in ALLOWED_LEAVE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="leave_type must be Sick, Casual, or Earned",
        )


def validate_dates(start_date: date, end_date: date):
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be greater than or equal to start_date",
        )

    if start_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Leave cannot be applied for past dates",
        )


def get_used_leave_days(
    db: Session,
    employee_id: int,
    leave_type: str,
) -> int:
    current_year = date.today().year

    approved_leaves = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.leave_type == leave_type,
            LeaveRequest.status == "Approved",
            LeaveRequest.start_date >= date(current_year, 1, 1),
            LeaveRequest.start_date <= date(current_year, 12, 31),
        )
        .all()
    )

    used_days = 0

    for leave in approved_leaves:
        used_days += leave.total_days

    return used_days


def check_overlap(
    db: Session,
    employee_id: int,
    start_date: date,
    end_date: date,
    exclude_leave_id: int | None = None,
):
    query = db.query(LeaveRequest).filter(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.status.in_(["Pending", "Approved"]),
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date,
    )

    if exclude_leave_id is not None:
        query = query.filter(LeaveRequest.id != exclude_leave_id)

    existing_leave = query.first()

    if existing_leave:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Leave dates overlap with an existing leave request",
        )


@router.post(
    "",
    response_model=LeaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_leave(
    leave_data: LeaveCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_leave_type(leave_data.leave_type)

    validate_dates(
        leave_data.start_date,
        leave_data.end_date,
    )

    employee = (
        db.query(Employee)
        .filter(Employee.id == leave_data.employee_id)
        .first()
    )

    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive employees cannot apply for leave",
        )

    if current_user.role == "Employee":
        if employee.email != current_user.email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can apply leave only for themselves",
            )

    total_days = calculate_weekdays(
        leave_data.start_date,
        leave_data.end_date,
    )

    if total_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected date range contains no working days",
        )

    check_overlap(
        db,
        leave_data.employee_id,
        leave_data.start_date,
        leave_data.end_date,
    )

    allowed_days = ALLOWED_LEAVE_TYPES[leave_data.leave_type]
    used_days = get_used_leave_days(
        db,
        leave_data.employee_id,
        leave_data.leave_type,
    )

    if used_days + total_days > allowed_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient {leave_data.leave_type} leave balance. "
                f"Available: {allowed_days - used_days} days"
            ),
        )

    leave = LeaveRequest(
        employee_id=leave_data.employee_id,
        leave_type=leave_data.leave_type,
        start_date=leave_data.start_date,
        end_date=leave_data.end_date,
        total_days=total_days,
        reason=leave_data.reason,
        status="Pending",
        approved_by=None,
        rejection_reason=None,
    )

    db.add(leave)
    db.commit()
    db.refresh(leave)

    return leave


@router.get(
    "",
    response_model=list[LeaveResponse],
)
def get_leaves(
    status_filter: str | None = Query(
        default=None,
        alias="status",
    ),
    leave_type: str | None = None,
    employee_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR", "Employee")
    ),
):
    query = db.query(LeaveRequest)

    if current_user.role == "Employee":
        employee = (
            db.query(Employee)
            .filter(Employee.email == current_user.email)
            .first()
        )

        if employee is None:
            return []

        query = query.filter(
            LeaveRequest.employee_id == employee.id
        )

    if status_filter:
        query = query.filter(
            LeaveRequest.status == status_filter
        )

    if leave_type:
        query = query.filter(
            LeaveRequest.leave_type == leave_type
        )

    if employee_id is not None:
        query = query.filter(
            LeaveRequest.employee_id == employee_id
        )

    if from_date is not None:
        query = query.filter(
            LeaveRequest.start_date >= from_date
        )

    if to_date is not None:
        query = query.filter(
            LeaveRequest.end_date <= to_date
        )

    return (
        query
        .order_by(LeaveRequest.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get(
    "/{leave_id}",
    response_model=LeaveResponse,
)
def get_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    leave = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.id == leave_id)
        .first()
    )

    if leave is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found",
        )

    if current_user.role == "Employee":
        employee = (
            db.query(Employee)
            .filter(Employee.id == leave.employee_id)
            .first()
        )

        if employee is None or employee.email != current_user.email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can view only their own leave requests",
            )

    return leave


@router.put(
    "/{leave_id}/approve",
    response_model=LeaveResponse,
)
def approve_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
):
    leave = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.id == leave_id)
        .first()
    )

    if leave is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found",
        )

    if leave.status != "Pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only Pending leaves can be approved",
        )

    employee = (
        db.query(Employee)
        .filter(Employee.id == leave.employee_id)
        .first()
    )

    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if current_user.role == "HR" and employee.email == current_user.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR cannot approve their own leave",
        )

    allowed_days = ALLOWED_LEAVE_TYPES[leave.leave_type]
    used_days = get_used_leave_days(
        db,
        leave.employee_id,
        leave.leave_type,
    )

    if used_days + leave.total_days > allowed_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient leave balance",
        )

    leave.status = "Approved"
    leave.approved_by = current_user.id
    leave.rejection_reason = None

    db.commit()
    db.refresh(leave)

    return leave


@router.put(
    "/{leave_id}/reject",
    response_model=LeaveResponse,
)
def reject_leave(
    leave_id: int,
    rejection_data: LeaveReject,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
):
    leave = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.id == leave_id)
        .first()
    )

    if leave is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found",
        )

    if leave.status != "Pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only Pending leaves can be rejected",
        )

    leave.status = "Rejected"
    leave.approved_by = current_user.id
    leave.rejection_reason = rejection_data.rejection_reason

    db.commit()
    db.refresh(leave)

    return leave


@router.put(
    "/{leave_id}/cancel",
    response_model=LeaveResponse,
)
def cancel_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    leave = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.id == leave_id)
        .first()
    )

    if leave is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found",
        )

    if leave.status != "Pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only Pending leaves can be cancelled",
        )

    employee = (
        db.query(Employee)
        .filter(Employee.id == leave.employee_id)
        .first()
    )

    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if current_user.role == "Employee":
        if employee.email != current_user.email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can cancel only their own leave requests",
            )

    leave.status = "Cancelled"

    db.commit()
    db.refresh(leave)

    return leave

@router.get(
    "/employees/{employee_id}/leave-balance"
)
def get_leave_balance(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee = (
        db.query(Employee)
        .filter(Employee.id == employee_id)
        .first()
    )

    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if current_user.role == "Employee":
        if employee.email != current_user.email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees can view only their own leave balance",
            )

    balance = {}

    for leave_type, allowed_days in ALLOWED_LEAVE_TYPES.items():
        used_days = get_used_leave_days(
            db,
            employee_id,
            leave_type,
        )

        balance[leave_type] = {
            "allowed": allowed_days,
            "used": used_days,
            "remaining": allowed_days - used_days,
        }

    return {
        "employee_id": employee_id,
        "balance": balance,
    }