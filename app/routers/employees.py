from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.user import User
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
)

router = APIRouter(
    prefix="/employees",
    tags=["Employees"],
)

ALLOWED_EMPLOYMENT_TYPES = {
    "Full-Time",
    "Part-Time",
    "Intern",
    "Contract",
}

LEAVE_BALANCES = {
    "Sick": 12,
    "Casual": 10,
    "Earned": 15,
}


def validate_employment_type(employment_type: str):
    if employment_type not in ALLOWED_EMPLOYMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "employment_type must be one of: "
                "Full-Time, Part-Time, Intern, Contract"
            ),
        )


def validate_joining_date(joining_date: date):
    if joining_date > date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_of_joining cannot be in the future",
        )


def calculate_used_leave_days(
    db: Session,
    employee_id: int,
    leave_type: str,
):
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


@router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_employee(
    employee_data: EmployeeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
):
    validate_employment_type(employee_data.employment_type)
    validate_joining_date(employee_data.date_of_joining)

    department = (
        db.query(Department)
        .filter(Department.id == employee_data.department_id)
        .first()
    )

    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    if not department.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign employee to an inactive department",
        )

    existing_code = (
        db.query(Employee)
        .filter(
            Employee.employee_code == employee_data.employee_code
        )
        .first()
    )

    if existing_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee code already exists",
        )

    existing_email = (
        db.query(Employee)
        .filter(Employee.email == employee_data.email)
        .first()
    )

    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee email already exists",
        )

    employee = Employee(
        employee_code=employee_data.employee_code,
        name=employee_data.name,
        email=employee_data.email,
        phone=employee_data.phone,
        department_id=employee_data.department_id,
        designation=employee_data.designation,
        salary=employee_data.salary,
        date_of_joining=employee_data.date_of_joining,
        employment_type=employee_data.employment_type,
        is_active=True,
    )

    db.add(employee)
    db.commit()
    db.refresh(employee)

    return employee


@router.get("", response_model=list[EmployeeResponse])
def get_employees(
    name: str | None = None,
    department_id: int | None = None,
    designation: str | None = None,
    employment_type: str | None = None,
    is_active: bool | None = None,
    sort_by: str | None = Query(
        default=None,
        pattern="^(name|salary|date_of_joining)$",
    ),
    order: str = Query(
        default="asc",
        pattern="^(asc|desc)$",
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR", "Employee")
    ),
):
    query = db.query(Employee)

    # Employee users can view only their own employee record.
    if current_user.role == "Employee":
        query = query.filter(
            Employee.email == current_user.email
        )

    if name:
        query = query.filter(
            Employee.name.ilike(f"%{name}%")
        )

    if department_id is not None:
        query = query.filter(
            Employee.department_id == department_id
        )

    if designation:
        query = query.filter(
            Employee.designation.ilike(f"%{designation}%")
        )

    if employment_type:
        query = query.filter(
            Employee.employment_type == employment_type
        )

    if is_active is not None:
        query = query.filter(
            Employee.is_active == is_active
        )

    if sort_by == "name":
        column = Employee.name
    elif sort_by == "salary":
        column = Employee.salary
    elif sort_by == "date_of_joining":
        column = Employee.date_of_joining
    else:
        column = None

    if column is not None:
        if order == "desc":
            query = query.order_by(column.desc())
        else:
            query = query.order_by(column.asc())

    return (
        query
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get(
    "/{employee_id}/leaves",
)
def get_employee_leaves(
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
                detail="Employees can view only their own leaves",
            )

    return (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.employee_id == employee_id
        )
        .order_by(LeaveRequest.id.desc())
        .all()
    )


@router.get(
    "/{employee_id}/leave-balance",
)
def get_employee_leave_balance(
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

    for leave_type, allowed_days in LEAVE_BALANCES.items():
        used_days = calculate_used_leave_days(
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


@router.get(
    "/{employee_id}",
    response_model=EmployeeResponse,
)
def get_employee(
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
                detail="Employees can view only their own details",
            )

    return employee


@router.put(
    "/{employee_id}",
    response_model=EmployeeResponse,
)
def update_employee(
    employee_id: int,
    employee_data: EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
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

    if employee_data.employee_code is not None:
        existing_code = (
            db.query(Employee)
            .filter(
                Employee.employee_code
                == employee_data.employee_code,
                Employee.id != employee_id,
            )
            .first()
        )

        if existing_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Employee code already exists",
            )

        employee.employee_code = employee_data.employee_code

    if employee_data.email is not None:
        existing_email = (
            db.query(Employee)
            .filter(
                Employee.email == employee_data.email,
                Employee.id != employee_id,
            )
            .first()
        )

        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Employee email already exists",
            )

        employee.email = employee_data.email

    if employee_data.name is not None:
        employee.name = employee_data.name

    if employee_data.phone is not None:
        employee.phone = employee_data.phone

    if employee_data.department_id is not None:
        department = (
            db.query(Department)
            .filter(
                Department.id
                == employee_data.department_id
            )
            .first()
        )

        if department is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Department not found",
            )

        if not department.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot assign employee to an inactive department",
            )

        employee.department_id = (
            employee_data.department_id
        )

    if employee_data.designation is not None:
        employee.designation = employee_data.designation

    if employee_data.salary is not None:
        employee.salary = employee_data.salary

    if employee_data.date_of_joining is not None:
        validate_joining_date(
            employee_data.date_of_joining
        )
        employee.date_of_joining = (
            employee_data.date_of_joining
        )

    if employee_data.employment_type is not None:
        validate_employment_type(
            employee_data.employment_type
        )
        employee.employment_type = (
            employee_data.employment_type
        )

    if employee_data.is_active is not None:
        employee.is_active = (
            employee_data.is_active
        )

    db.commit()
    db.refresh(employee)

    return employee


@router.delete("/{employee_id}")
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("Admin", "HR")
    ),
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

    if not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee is already inactive",
        )

    employee.is_active = False

    db.commit()

    return {
        "message": "Employee deactivated successfully"
    }