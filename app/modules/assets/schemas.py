from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MachineInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    production_area: str = Field(min_length=1, max_length=100)


class MachineUpdate(MachineInput):
    is_active: bool
    version: int = Field(ge=1)


class GroupInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)


class GroupUpdate(GroupInput):
    is_active: bool
    version: int = Field(ge=1)


class PairInput(BaseModel):
    machine_1_id: int = Field(gt=0)
    machine_2_id: int = Field(gt=0)


class PairGroupInput(BaseModel):
    machine_group_id: int | None = Field(default=None, gt=0)


class ActiveInput(BaseModel):
    is_active: bool
    version: int = Field(ge=1)


PairStatus = Literal["active", "inactive"]
