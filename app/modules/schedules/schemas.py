from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScheduleBatchCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    production_dates: list[date] = Field(min_length=1, max_length=62)
    shift_id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    planned_quantity: int = Field(gt=0)

    @field_validator("production_dates")
    @classmethod
    def unique_dates(cls, value: list[date]) -> list[date]:
        if len(value) != len(set(value)):
            raise ValueError("Không chọn trùng ngày.")
        return value


class ScheduleUpdate(BaseModel):
    production_date: date
    shift_id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    planned_quantity: int = Field(gt=0)
    version: int = Field(ge=1)
