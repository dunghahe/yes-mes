from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DetectedAt = Literal["SX", "BAVIA"]


class DefectCodeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    defect_group: str = Field(default="", max_length=100)
    detected_at: DetectedAt


class DefectCodeUpdate(DefectCodeCreate):
    is_active: bool
    version: int = Field(ge=1)
