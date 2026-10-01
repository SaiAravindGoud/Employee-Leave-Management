from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    department_name: str = Field(min_length=2, max_length=100)
    location: str = Field(min_length=2, max_length=100)


class DepartmentUpdate(BaseModel):
    department_name: str | None = Field(default=None, min_length=2, max_length=100)
    location: str | None = Field(default=None, min_length=2, max_length=100)
    is_active: bool | None = None


class DepartmentResponse(BaseModel):
    id: int
    department_name: str
    location: str
    is_active: bool

    model_config = {"from_attributes": True}