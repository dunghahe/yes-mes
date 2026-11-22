from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Disposition = Literal["scrap", "repair"]


class LotQcDefectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defect_code_id: int = Field(gt=0)
    machine_id: int = Field(gt=0)
    disposition: Disposition
    quantity: int = Field(gt=0)


class LotQcInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspected_date: date
    shift_id: int = Field(gt=0)
    qc_employee_id: int = Field(gt=0)
    version: int = Field(ge=0)
    quantity_ok: int = Field(ge=0)
    quantity_ng: int = Field(ge=0)
    ng_scrap: int = Field(ge=0)
    ng_repair: int = Field(ge=0)
    defects: list[LotQcDefectInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def defect_totals_match(self):
        scrap = sum(row.quantity for row in self.defects if row.disposition == "scrap")
        repair = sum(row.quantity for row in self.defects if row.disposition == "repair")
        if scrap + repair != self.quantity_ng:
            raise ValueError("Tổng chi tiết lỗi phải khớp tổng NG.")
        if (scrap, repair) != (self.ng_scrap, self.ng_repair):
            raise ValueError("NG hủy và NG sửa phải khớp chi tiết lỗi.")
        if (self.quantity_ng or self.ng_scrap or self.ng_repair) and not self.defects:
            raise ValueError("Có NG thì cần nhập dạng lỗi, số lượng và máy.")
        return self


class QcPairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_report_pair_id: int = Field(gt=0)
    ng_scrap: int = Field(ge=0)
    ng_repair: int = Field(ge=0)


class QcCheckStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(ge=1, le=4)
    ng_scrap: int = Field(ge=0)
    ng_repair: int = Field(ge=0)
    qc_employee_id: int = Field(gt=0)


class QcInspectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspected_date: date
    shift_id: int = Field(gt=0)
    version: int = Field(ge=0)
    pairs: list[QcPairInput] = Field(min_length=1, max_length=40)
    steps: list[QcCheckStepInput] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_totals(self):
        pair_ids = [row.daily_report_pair_id for row in self.pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Không được nhập trùng cặp máy trong phần QC.")
        step_numbers = [row.step_number for row in self.steps]
        if sorted(step_numbers) != [1, 2, 3, 4]:
            raise ValueError("Cần nhập đủ 4 nội dung kiểm soát QC.")
        pair_scrap = sum(row.ng_scrap for row in self.pairs)
        pair_repair = sum(row.ng_repair for row in self.pairs)
        step_scrap = sum(row.ng_scrap for row in self.steps)
        step_repair = sum(row.ng_repair for row in self.steps)
        if (pair_scrap, pair_repair) != (step_scrap, step_repair):
            raise ValueError("Tổng NG hủy và NG sửa ở 4 bước phải khớp với phần QC theo cặp máy.")
        return self


class QcSectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspected_date: date
    shift_id: int = Field(gt=0)
    version: int = Field(ge=0)


class QcPairSectionInput(QcSectionMetadata):
    pairs: list[QcPairInput] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def unique_pairs(self):
        pair_ids = [row.daily_report_pair_id for row in self.pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Không được nhập trùng cặp máy trong phần QC.")
        return self


class QcStepsSectionInput(QcSectionMetadata):
    steps: list[QcCheckStepInput] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_steps(self):
        step_numbers = [row.step_number for row in self.steps]
        if len(step_numbers) != len(set(step_numbers)):
            raise ValueError("Không được nhập trùng nội dung kiểm soát QC.")
        return self


class QcPartialSaveInput(QcSectionMetadata):
    pairs: list[QcPairInput] | None = Field(default=None, max_length=40)
    steps: list[QcCheckStepInput] | None = Field(default=None, max_length=4)

    @model_validator(mode="after")
    def validate_partial_sections(self):
        if not self.pairs and not self.steps:
            raise ValueError("Nhập ít nhất một phần QC đủ thông tin rồi lưu.")
        if self.pairs is not None:
            pair_ids = [row.daily_report_pair_id for row in self.pairs]
            if len(pair_ids) != len(set(pair_ids)):
                raise ValueError("Không được nhập trùng cặp máy trong phần QC.")
        if self.steps is not None:
            step_numbers = [row.step_number for row in self.steps]
            if len(step_numbers) != len(set(step_numbers)):
                raise ValueError("Không được nhập trùng nội dung kiểm soát QC.")
        return self
