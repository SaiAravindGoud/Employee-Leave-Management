from datetime import date
from calendar import monthrange

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.user import User


router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
):
    total_employees = (
        db.query(Employee)
        .count()
    )

    active_employees = (
        db.query(Employee)
        .filter(Employee.is_active.is_(True))
        .count()
    )

    employees_per_department = (
        db.query(
            Department.department_name,
            func.count(Employee.id).label("employee_count"),
        )
        .outerjoin(
            Employee,
            Employee.department_id == Department.id,
        )
        .filter(Employee.is_active.is_(True))
        .group_by(Department.id, Department.department_name)
        .all()
    )

    pending_leave_requests = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.status == "Pending")
        .count()
    )

    today = date.today()

    employees_on_leave_today = (
        db.query(Employee)
        .join(
            LeaveRequest,
            LeaveRequest.employee_id == Employee.id,
        )
        .filter(
            Employee.is_active.is_(True),
            LeaveRequest.status == "Approved",
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today,
        )
        .all()
    )

    return {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "employees_per_department": [
            {
                "department_name": department_name,
                "employee_count": employee_count,
            }
            for department_name, employee_count
            in employees_per_department
        ],
        "pending_leave_requests": pending_leave_requests,
        "employees_on_leave_today": [
            {
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "name": employee.name,
            }
            for employee in employees_on_leave_today
        ],
    }


@router.get("/leave-summary")
def leave_summary(
    year: int = Query(
        default=date.today().year,
        ge=2000,
        le=2100,
    ),
    month: int = Query(
        default=date.today().month,
        ge=1,
        le=12,
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
):
    first_day = date(year, month, 1)
    last_day = date(
        year,
        month,
        monthrange(year, month)[1],
    )

    summary = (
        db.query(
            LeaveRequest.leave_type,
            LeaveRequest.status,
            func.count(LeaveRequest.id).label(
                "leave_count"
            ),
        )
        .filter(
            LeaveRequest.start_date >= first_day,
            LeaveRequest.start_date <= last_day,
        )
        .group_by(
            LeaveRequest.leave_type,
            LeaveRequest.status,
        )
        .all()
    )

    return {
        "year": year,
        "month": month,
        "summary": [
            {
                "leave_type": leave_type,
                "status": leave_status,
                "leave_count": leave_count,
            }
            for leave_type, leave_status, leave_count
            in summary
        ],
    }