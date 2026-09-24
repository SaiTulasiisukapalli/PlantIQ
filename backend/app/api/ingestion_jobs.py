from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import (
    Asset,
    Channel,
    File,
    IngestionJob,
    MappingTemplate,
    Reading,
)
from app.schemas.ingestion_job import (
    IngestionJobCreate,
    IngestionJobResponse,
)


router = APIRouter(
    prefix="/ingestion-jobs",
    tags=["Ingestion Jobs"],
)


@router.post(
    "",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ingestion_job(
    job: IngestionJobCreate,
    db: Session = Depends(get_db),
):
    file_record = db.get(File, job.file_id)

    if file_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    template = db.get(
        MappingTemplate,
        job.template_id,
    )

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapping template not found",
        )

    if file_record.org_id != template.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File and mapping template belong to different organizations",
        )

    new_job = IngestionJob(
        file_id=job.file_id,
        template_id=job.template_id,
        status="pending",
        qc_summary={},
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    return new_job


@router.get(
    "",
    response_model=list[IngestionJobResponse],
)
def get_ingestion_jobs(
    file_id: UUID | None = None,
    template_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    query = select(IngestionJob)

    if file_id is not None:
        query = query.where(
            IngestionJob.file_id == file_id
        )

    if template_id is not None:
        query = query.where(
            IngestionJob.template_id == template_id
        )

    query = query.order_by(
        IngestionJob.created_at.desc()
    )

    result = db.execute(query)

    return result.scalars().all()


@router.get(
    "/{job_id}",
    response_model=IngestionJobResponse,
)
def get_ingestion_job(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    job = db.get(
        IngestionJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    return job


@router.post(
    "/{job_id}/run",
    response_model=IngestionJobResponse,
)
def run_ingestion_job(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    job = db.get(
        IngestionJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    if job.status == "done":
        return job

    file_record = db.get(
        File,
        job.file_id,
    )

    if file_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    template = db.get(
        MappingTemplate,
        job.template_id,
    )

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapping template not found",
        )

    try:
        job.status = "profiling"
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        db.commit()

        file_path = Path(file_record.path)

        if not file_path.exists():
            backend_root = Path(__file__).resolve().parents[2]
            file_path = backend_root / file_record.path

        if not file_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {file_record.path}"
            )

        df = pd.read_csv(file_path)

        if df.empty:
            raise ValueError(
                "CSV file contains no rows"
            )

        mappings = template.mappings

        timestamp_column = mappings.get("timestamp")
        source_key_column = mappings.get("source_key")
        power_column = mappings.get("power_ac")

        if not timestamp_column:
            raise ValueError(
                "Mapping template does not contain a timestamp mapping"
            )

        if not source_key_column:
            raise ValueError(
                "Mapping template does not contain a source_key mapping"
            )

        if not power_column:
            raise ValueError(
                "Mapping template does not contain a power_ac mapping"
            )

        required_columns = [
            timestamp_column,
            source_key_column,
            power_column,
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:
            raise ValueError(
                f"Required CSV columns not found: {missing_columns}"
            )

        job.status = "ingesting"
        db.commit()

        df[timestamp_column] = pd.to_datetime(
            df[timestamp_column],
            dayfirst=True,
            errors="coerce",
        )

        df[power_column] = pd.to_numeric(
            df[power_column],
            errors="coerce",
        )

        df[source_key_column] = (
            df[source_key_column]
            .astype("string")
            .str.strip()
        )

        invalid_timestamp_count = int(
            df[timestamp_column].isna().sum()
        )

        invalid_power_count = int(
            df[power_column].isna().sum()
        )

        invalid_source_key_count = int(
            df[source_key_column].isna().sum()
        )

        valid_df = df[
            df[timestamp_column].notna()
            & df[power_column].notna()
            & df[source_key_column].notna()
        ].copy()

        if valid_df.empty:
            raise ValueError(
                "No valid timestamp/source_key/power rows found in CSV"
            )

        assets = db.execute(
            select(Asset).where(
                Asset.plant_id == (
                    select(Asset.plant_id)
                    .where(Asset.metadata_["source_key"].as_string() == valid_df.iloc[0][source_key_column])
                    .limit(1)
                    .scalar_subquery()
                )
            )
        ).scalars().all()

        asset_by_source_key = {}

        for asset in assets:
            metadata = asset.metadata_ or {}
            source_key = metadata.get("source_key")

            if source_key:
                asset_by_source_key[source_key] = asset

        if not asset_by_source_key:
            raise ValueError(
                "No assets with SOURCE_KEY mappings were found"
            )

        channels = db.execute(
            select(Channel).where(
                Channel.canonical_key == "power_ac",
                Channel.source_name == "AC Power",
            )
        ).scalars().all()

        channel_by_asset_id = {
            channel.asset_id: channel
            for channel in channels
        }

        source_keys = set(
            valid_df[source_key_column].unique()
        )

        unknown_source_keys = sorted(
            source_keys - set(asset_by_source_key.keys())
        )

        if unknown_source_keys:
            raise ValueError(
                "SOURCE_KEY values are not mapped to assets: "
                + ", ".join(unknown_source_keys)
            )

        inserted = 0
        updated = 0
        skipped = 0

        min_time = None
        max_time = None

        for row in valid_df.itertuples(index=False):
            row_dict = row._asdict()

            timestamp = row_dict[timestamp_column]
            source_key = row_dict[source_key_column]
            power_ac = row_dict[power_column]

            asset = asset_by_source_key.get(source_key)

            if asset is None:
                skipped += 1
                continue

            channel = channel_by_asset_id.get(asset.id)

            if channel is None:
                skipped += 1
                continue

            timestamp = timestamp.to_pydatetime()

            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(
                    tzinfo=timezone.utc
                )

            value = float(power_ac)

            existing_reading = db.execute(
                select(Reading).where(
                    Reading.channel_id == channel.id,
                    Reading.ts == timestamp,
                )
            ).scalar_one_or_none()

            if existing_reading is not None:
                existing_reading.value = value
                existing_reading.quality = 0
                existing_reading.ingestion_job_id = job.id
                updated += 1
            else:
                reading = Reading(
                    channel_id=channel.id,
                    ts=timestamp,
                    value=value,
                    quality=0,
                    ingestion_job_id=job.id,
                )

                db.add(reading)
                inserted += 1

            if min_time is None or timestamp < min_time:
                min_time = timestamp

            if max_time is None or timestamp > max_time:
                max_time = timestamp

        db.flush()

        job.status = "qc"
        job.rows_total = len(df)
        job.time_min = min_time
        job.time_max = max_time

        job.qc_summary = {
            "rows_total": int(len(df)),
            "rows_valid": int(len(valid_df)),
            "rows_inserted": inserted,
            "rows_updated": updated,
            "rows_skipped": skipped,
            "invalid_timestamp": invalid_timestamp_count,
            "invalid_power_ac": invalid_power_count,
            "invalid_source_key": invalid_source_key_count,
            "unique_source_keys": len(source_keys),
            "unknown_source_keys": unknown_source_keys,
        }

        job.status = "done"
        job.finished_at = datetime.now(timezone.utc)
        job.error = None

        db.commit()
        db.refresh(job)

        return job

    except Exception as exc:
        db.rollback()

        job = db.get(
            IngestionJob,
            job_id,
        )

        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(job)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        )
