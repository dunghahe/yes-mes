from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EmployeeType = Literal["operator", "qc", "repair", "engineering"]


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    employee_type: EmployeeType


class EmployeeUpdate(EmployeeCreate):
    is_active: bool
    version: int = Field(ge=1)
