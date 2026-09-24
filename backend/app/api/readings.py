from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, text, cast, Interval
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Channel, Reading
from app.schemas.reading import ReadingCreate, ReadingResponse
from app.schemas.reading_summary import ReadingSummaryResponse
from app.schemas.reading_aggregate import ReadingAggregateResponse


router = APIRouter(
    prefix="/readings",
    tags=["Readings"],
)


@router.post(
    "",
    response_model=ReadingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reading(
    reading: ReadingCreate,
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, reading.channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    new_reading = Reading(
        channel_id=reading.channel_id,
        ts=reading.ts,
        value=reading.value,
        quality=reading.quality,
        ingestion_job_id=reading.ingestion_job_id,
    )

    db.add(new_reading)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reading already exists for this channel and timestamp",
        )

    db.refresh(new_reading)

    return new_reading
@router.get(
    "/summary",
    response_model=ReadingSummaryResponse,
)
def get_readings_summary(
    channel_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    query = select(
        func.count(Reading.value).label("reading_count"),
        func.avg(Reading.value).label("average_value"),
        func.min(Reading.value).label("minimum_value"),
        func.max(Reading.value).label("maximum_value"),
    ).where(
        Reading.channel_id == channel_id
    )

    if start is not None:
        query = query.where(
            Reading.ts >= start
        )

    if end is not None:
        query = query.where(
            Reading.ts <= end
        )

    result = db.execute(query).one()

    return ReadingSummaryResponse(
        channel_id=channel_id,
        start=start,
        end=end,
        reading_count=result.reading_count,
        average_value=(
            float(result.average_value)
            if result.average_value is not None
            else None
        ),
        minimum_value=(
            float(result.minimum_value)
            if result.minimum_value is not None
            else None
        ),
        maximum_value=(
            float(result.maximum_value)
            if result.maximum_value is not None
            else None
        ),
    )
@router.get(
    "/aggregate",
    response_model=list[ReadingAggregateResponse],
)
def get_readings_aggregate(
    channel_id: UUID,
    start: datetime,
    end: datetime,
    interval: str = "hour",
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    allowed_intervals = {
        "5min": "5 minutes",
        "hour": "1 hour",
        "day": "1 day",
    }

    if interval not in allowed_intervals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid interval. Use one of: 5min, hour, day",
        )

    if start >= end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start must be before end",
        )

    bucket_interval = allowed_intervals[interval]

    bucket_expression = func.time_bucket(
        cast(bucket_interval, Interval),
        Reading.ts,
    )

    query = (
        select(
            bucket_expression.label("bucket"),
            func.count(Reading.value).label("reading_count"),
            func.avg(Reading.value).label("average_value"),
            func.min(Reading.value).label("minimum_value"),
            func.max(Reading.value).label("maximum_value"),
        )
        .where(
            Reading.channel_id == channel_id,
            Reading.ts >= start,
            Reading.ts <= end,
        )
        .group_by(bucket_expression)
        .order_by(bucket_expression.asc())
    )

    result = db.execute(query).all()

    return [
        ReadingAggregateResponse(
            channel_id=channel_id,
            interval=interval,
            start=row.bucket,
            end=row.bucket,
            reading_count=row.reading_count,
            average_value=(
                float(row.average_value)
                if row.average_value is not None
                else None
            ),
            minimum_value=(
                float(row.minimum_value)
                if row.minimum_value is not None
                else None
            ),
            maximum_value=(
                float(row.maximum_value)
                if row.maximum_value is not None
                else None
            ),
        )
        for row in result
    ]