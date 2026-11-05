from pydantic import BaseModel, Field, field_validator


class BlankRequestCreate(BaseModel):
    schedule_id: int = Field(gt=0)
    blank_quantity: int = Field(gt=0)
    machine_group_id: int = Field(gt=0)
    machine_pair_ids: list[int] = Field(min_length=1, max_length=40)
    operator_ids: list[int] = Field(min_length=1, max_length=40)

    @field_validator("machine_pair_ids", "operator_ids")
    @classmethod
    def unique_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Không chọn trùng mục.")
        if any(item <= 0 for item in value):
            raise ValueError("Giá trị phải lớn hơn 0.")
        return value
