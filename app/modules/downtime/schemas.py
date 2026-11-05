from pydantic import BaseModel, ConfigDict, Field


class DowntimeReasonCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)


class DowntimeReasonUpdate(DowntimeReasonCreate):
    is_active: bool
    version: int = Field(ge=1)
