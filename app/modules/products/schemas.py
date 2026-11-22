from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    cycle_time_seconds: Decimal = Field(gt=0, max_digits=12, decimal_places=3)


class ProductUpdate(ProductCreate):
    is_active: bool
    version: int = Field(ge=1)
