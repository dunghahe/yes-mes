from json import JSONDecodeError
from typing import Any

from fastapi import HTTPException, Request
from pydantic import ValidationError


async def read_json(request: Request) -> Any:
    try:
        return await request.json()
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Dữ liệu JSON không hợp lệ.") from exc


def validation_details(error: ValidationError) -> list[dict[str, Any]]:
    # Validator context may contain exception objects, which JSONResponse cannot encode.
    return [
        {
            "loc": list(item["loc"]),
            "msg": item["msg"].removeprefix("Value error, "),
            "type": item["type"],
        }
        for item in error.errors(include_context=False, include_input=False)
    ]
