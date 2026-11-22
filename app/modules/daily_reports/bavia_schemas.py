from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class BaviaReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(gt=0)
    report_date: date
    shift_id: int = Field(gt=0)
    employee_id: int = Field(gt=0)
    quantity_produced: int = Field(ge=0)
    version: int = Field(default=0, ge=0)


class BaviaQcInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspected_date: date
    shift_id: int = Field(gt=0)
    qc_employee_id: int = Field(gt=0)
    ng_scrap: int = Field(ge=0)
    ng_repair: int = Field(ge=0)
    version: int = Field(default=0, ge=0)
