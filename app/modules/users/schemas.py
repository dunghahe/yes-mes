from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "planning", "engineering", "warehouse", "data_entry", "manager"]
PermissionModule = Literal[
    "master",
    "orders",
    "schedules",
    "blank_requests",
    "daily_reports",
    "qc",
    "repairs",
    "reports",
    "audit",
]


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role
    is_active: bool
    version: int = Field(ge=1)


class PermissionInput(BaseModel):
    module: PermissionModule
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    version: int = Field(default=0, ge=0)
