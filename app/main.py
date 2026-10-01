from fastapi import FastAPI

from app.routers.auth import router as auth_router
from app.routers.departments import router as departments_router
from app.routers.employees import router as employees_router
from app.routers.leaves import router as leaves_router
from app.routers.reports import router as reports_router


app = FastAPI(
    title="Employee & Leave Management System",
    description="HR management backend using FastAPI, MySQL, JWT and Alembic",
    version="1.0.0",
)


app.include_router(auth_router)
app.include_router(departments_router)
app.include_router(employees_router)
app.include_router(leaves_router)
app.include_router(reports_router)


@app.get("/")
def root():
    return {
        "message": "Employee & Leave Management System API is running"
    }