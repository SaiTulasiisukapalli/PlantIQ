from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReadingSummaryResponse(BaseModel):
    channel_id: UUID
    start: datetime | None
    end: datetime | None
    reading_count: int
    average_value: float | None
    minimum_value: float | None
    maximum_value: float | None