from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProcessType = Literal["FULL", "SX_ONLY", "BAVIA_ONLY"]


class OrderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    po_no: str = Field(min_length=1, max_length=100)
    product_id: int = Field(gt=0)
    ordered_quantity: int = Field(gt=0)
    lot_size: int = Field(gt=0)
    process_type: ProcessType
    raw_material_code: str = Field(min_length=1, max_length=100)
    drawing_number: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=1, max_length=30)
    material: str = Field(min_length=1, max_length=100)
    blank_size: str = Field(min_length=1, max_length=100)
    order_received_date: date
    notes: str | None = Field(default=None, max_length=2000)


class OrderUpdate(OrderCreate):
    version: int = Field(ge=1)
