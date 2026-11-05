from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShiftCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    start_time: time
    end_time: time
    planned_break_minutes: int = Field(ge=0)
    crosses_midnight: bool

    @model_validator(mode="after")
    def validate_shift_window(self) -> "ShiftCreate":
        if self.start_time == self.end_time:
            raise ValueError("Giờ bắt đầu và kết thúc không được trùng nhau.")
        crosses_by_time = self.end_time < self.start_time
        if self.crosses_midnight != crosses_by_time:
            raise ValueError("Cờ qua nửa đêm phải khớp với giờ bắt đầu và kết thúc.")
        start_seconds = (
            self.start_time.hour * 3600 + self.start_time.minute * 60 + self.start_time.second
        )
        end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60 + self.end_time.second
        duration_seconds = (end_seconds - start_seconds) % (24 * 60 * 60)
        if self.planned_break_minutes * 60 > duration_seconds:
            raise ValueError("Thời gian nghỉ không thể dài hơn tổng thời lượng kíp.")
        return self


class ShiftUpdate(ShiftCreate):
    is_active: bool
    version: int = Field(ge=1)
