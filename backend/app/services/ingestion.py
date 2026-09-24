from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Channel, File, IngestionJob, MappingTemplate, Reading


def process_ingestion_job(
    db: Session,
    job_id: UUID,
) -> IngestionJob:
    job = db.get(IngestionJob, job_id)

    if job is None:
        raise ValueError("Ingestion job not found")

    if job.status == "completed":
        return job

    file_record = db.get(File, job.file_id)

    if file_record is None:
        raise ValueError("File not found")

    template = db.get(MappingTemplate, job.template_id)

    if template is None:
        raise ValueError("Mapping template not found")

    file_path = Path(file_record.path)

    if not file_path.exists():
        backend_root = Path(__file__).resolve().parents[2]
        file_path = backend_root / file_record.path

    if not file_path.exists():
        raise FileNotFoundError(
            f"CSV file not found: {file_record.path}"
        )

    mappings = template.mappings

    timestamp_column = mappings.get("timestamp")
    source_key_column = mappings.get("source_key")
    power_ac_column = mappings.get("power_ac")

    if not timestamp_column:
        raise ValueError("Mapping template is missing timestamp mapping")

    if not source_key_column:
        raise ValueError("Mapping template is missing source_key mapping")

    if not power_ac_column:
        raise ValueError("Mapping template is missing power_ac mapping")

    job.status = "processing"
    job.started_at = datetime.now(timezone.utc)
    job.error = None
    job.qc_summary = {}

    db.commit()
    db.refresh(job)

    try:
        df = pd.read_csv(file_path)

        required_columns = {
            timestamp_column,
            source_key_column,
            power_ac_column,
        }

        missing_columns = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:
            raise ValueError(
                f"Missing required CSV columns: {missing_columns}"
            )

        rows_total = len(df)

        df[timestamp_column] = pd.to_datetime(
            df[timestamp_column],
            dayfirst=True,
            errors="coerce",
        )

        df[power_ac_column] = pd.to_numeric(
            df[power_ac_column],
            errors="coerce",
        )

        df[source_key_column] = (
            df[source_key_column]
            .astype("string")
            .str.strip()
        )

        invalid_timestamp = int(
            df[timestamp_column].isna().sum()
        )

        invalid_power = int(
            df[power_ac_column].isna().sum()
        )

        invalid_source_key = int(
            df[source_key_column].isna().sum()
        )

        valid_df = df[
            df[timestamp_column].notna()
            & df[power_ac_column].notna()
            & df[source_key_column].notna()
        ].copy()

        source_keys = set(
            valid_df[source_key_column].unique()
        )

        assets = db.execute(
            select(Asset).where(
                Asset.plant_id == template.org_id
            )
        ).scalars().all()

        asset_by_source_key = {}

        for asset in assets:
            metadata = asset.metadata_ or {}

            source_key = metadata.get("source_key")

            if source_key:
                asset_by_source_key[source_key] = asset

        channels = db.execute(
            select(Channel)
        ).scalars().all()

        channel_by_asset_id = {}

        for channel in channels:
            if channel.canonical_key == "power_ac":
                channel_by_asset_id[channel.asset_id] = channel

        unknown_source_keys = sorted(
            source_keys - set(asset_by_source_key.keys())
        )

        if unknown_source_keys:
            raise ValueError(
                "SOURCE_KEY values are not mapped to assets: "
                + ", ".join(unknown_source_keys)
            )

        inserted = 0
        skipped = 0

        min_time = None
        max_time = None

        for row in valid_df.itertuples(index=False):
            row_dict = row._asdict()

            timestamp = row_dict[timestamp_column]
            source_key = row_dict[source_key_column]
            power_ac = row_dict[power_ac_column]

            asset = asset_by_source_key.get(source_key)

            if asset is None:
                skipped += 1
                continue

            channel = channel_by_asset_id.get(asset.id)

            if channel is None:
                skipped += 1
                continue

            if timestamp.tzinfo is None:
                timestamp = timestamp.to_pydatetime().replace(
                    tzinfo=timezone.utc
                )
            else:
                timestamp = timestamp.to_pydatetime()

            value = float(power_ac)

            existing = db.execute(
                select(Reading).where(
                    Reading.channel_id == channel.id,
                    Reading.ts == timestamp,
                )
            ).scalar_one_or_none()

            if existing is not None:
                existing.value = value
                existing.quality = 0
                existing.ingestion_job_id = job.id
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

        job.status = "completed"
        job.rows_total = rows_total
        job.time_min = min_time
        job.time_max = max_time
        job.qc_summary = {
            "rows_total": rows_total,
            "rows_valid": len(valid_df),
            "rows_processed": inserted,
            "rows_skipped": skipped,
            "invalid_timestamp": invalid_timestamp,
            "invalid_power_ac": invalid_power,
            "invalid_source_key": invalid_source_key,
            "unique_source_keys": len(source_keys),
            "unknown_source_keys": unknown_source_keys,
        }
        job.finished_at = datetime.now(timezone.utc)
        job.error = None

        db.commit()
        db.refresh(job)

        return job

    except Exception as exc:
        db.rollback()

        job = db.get(IngestionJob, job_id)

        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(job)

        raise
