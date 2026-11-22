from pydantic import BaseModel, ConfigDict, Field


class ProductionSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_auto_close_pct: int = Field(ge=1, le=100)
    version: int = Field(ge=1)
