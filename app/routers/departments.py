from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models.department import Department
from app.models.employee import Employee
from app.schemas.department import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
)

router = APIRouter(
    prefix="/departments",
    tags=["Departments"],
)


@router.post(
    "",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_department(
    department_data: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("Admin")),
):
    existing_department = (
        db.query(Department)
        .filter(
            Department.department_name
            == department_data.department_name
        )
        .first()
    )

    if existing_department:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department name already exists",
        )

    department = Department(
        department_name=department_data.department_name,
        location=department_data.location,
        is_active=True,
    )

    db.add(department)
    db.commit()
    db.refresh(department)

    return department


@router.get(
    "",
    response_model=list[DepartmentResponse],
)
def get_departments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(
        require_roles("Admin", "HR", "Employee")
    ),
):
    return (
        db.query(Department)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get(
    "/{department_id}",
    response_model=DepartmentResponse,
)
def get_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(
        require_roles("Admin", "HR", "Employee")
    ),
):
    department = (
        db.query(Department)
        .filter(Department.id == department_id)
        .first()
    )

    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    return department


@router.put(
    "/{department_id}",
    response_model=DepartmentResponse,
)
def update_department(
    department_id: int,
    department_data: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("Admin")),
):
    department = (
        db.query(Department)
        .filter(Department.id == department_id)
        .first()
    )

    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    if department_data.department_name is not None:
        existing_department = (
            db.query(Department)
            .filter(
                Department.department_name
                == department_data.department_name,
                Department.id != department_id,
            )
            .first()
        )

        if existing_department:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Department name already exists",
            )

        department.department_name = (
            department_data.department_name
        )

    if department_data.location is not None:
        department.location = department_data.location

    if department_data.is_active is not None:
        department.is_active = department_data.is_active

    db.commit()
    db.refresh(department)

    return department


@router.delete("/{department_id}")
def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("Admin")),
):
    department = (
        db.query(Department)
        .filter(Department.id == department_id)
        .first()
    )

    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    active_employee = (
        db.query(Employee)
        .filter(
            Employee.department_id == department_id,
            Employee.is_active.is_(True),
        )
        .first()
    )

    if active_employee:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete department with active employees",
        )

    db.delete(department)
    db.commit()

    return {
        "message": "Department deleted successfully"
    }


@router.get("/{department_id}/employees")
def get_department_employees(
    department_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(
        require_roles("Admin", "HR", "Employee")
    ),
):
    department = (
        db.query(Department)
        .filter(Department.id == department_id)
        .first()
    )

    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    employees = (
        db.query(Employee)
        .filter(
            Employee.department_id == department_id,
            Employee.is_active.is_(True),
        )
        .all()
    )

    return employees