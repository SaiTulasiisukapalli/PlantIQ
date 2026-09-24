from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FileBase(BaseModel):
    org_id: UUID

    kind: Literal[
        "raw_upload",
        "report",
        "export",
    ]

    path: str
    original_name: str | None = None
    size_bytes: int | None = None
    created_by: UUID | None = None


class FileCreate(FileBase):
    pass


class FileResponse(FileBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )