from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RepairStage = Literal["QC", "QC_BAVIA"]


class RepairJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_id: int = Field(gt=0)
    production_lot_id: int = Field(gt=0)
    stage: RepairStage
    repair_employee_id: int = Field(gt=0)
    repair_date: date
    quantity_repaired: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)


class RepairRecheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    repair_code: str = Field(min_length=1, max_length=40)
    inspected_date: date
    shift_id: int = Field(gt=0)
    qc_employee_id: int = Field(gt=0)
    quantity_in: int = Field(gt=0)
    quantity_ok: int = Field(ge=0)
    ng_scrap: int = Field(ge=0)
    ng_repair: int = Field(ge=0)

    @field_validator("repair_code")
    @classmethod
    def normalize_repair_code(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def counts_must_match(self):
        if self.quantity_ok + self.ng_scrap + self.ng_repair != self.quantity_in:
            raise ValueError("OK + NG hủy + NG sửa phải bằng số lượng đưa vào QC lại.")
        return self
