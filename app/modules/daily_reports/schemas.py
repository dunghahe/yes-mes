from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DowntimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_id: int = Field(gt=0)
    minutes: int = Field(gt=0)


class ReportPairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_machine_pair_id: int = Field(gt=0)
    machine_pair_id: int = Field(gt=0)
    employee_id: int = Field(gt=0)
    downtime_recorded: bool = False
    quantity_produced: int = Field(ge=0)
    downtime: list[DowntimeInput] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_downtime(self):
        if self.downtime and not self.downtime_recorded:
            raise ValueError("Có phút dừng thì phải xác nhận biểu có ghi dừng máy.")
        return self


class DailyProductionReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blank_request_id: int = Field(gt=0)
    report_date: date
    shifts: list["ReportShiftInput"] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def unique_pairs_and_valid_times(self):
        shift_ids = [entry.shift_id for entry in self.shifts]
        if len(shift_ids) != len(set(shift_ids)):
            raise ValueError("Mỗi kíp chỉ thêm một lần trong báo cáo.")
        return self


class ReportShiftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shift_id: int = Field(gt=0)
    pairs: list[ReportPairInput] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def unique_machine_pairs(self):
        pair_ids = [entry.machine_pair_id for entry in self.pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Không chọn trùng cặp máy trong cùng một kíp.")
        source_ids = [entry.source_machine_pair_id for entry in self.pairs]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Không gửi trùng dòng cặp máy đã khai báo.")
        return self


DailyProductionReportCreate.model_rebuild()
