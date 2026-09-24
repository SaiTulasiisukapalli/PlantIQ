from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Asset, CanonicalSignal, Channel
from app.schemas.channel import ChannelCreate, ChannelResponse


router = APIRouter(
    prefix="/channels",
    tags=["Channels"],
)


@router.post(
    "",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_channel(
    channel: ChannelCreate,
    db: Session = Depends(get_db),
):
    asset = db.get(Asset, channel.asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )

    canonical_signal = db.get(
        CanonicalSignal,
        channel.canonical_key,
    )

    if canonical_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )

    existing_channel = db.execute(
        select(Channel).where(
            Channel.asset_id == channel.asset_id,
            Channel.canonical_key == channel.canonical_key,
            Channel.source_name == channel.source_name,
        )
    ).scalar_one_or_none()

    if existing_channel is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Channel already exists for this asset, canonical signal, and source",
        )

    new_channel = Channel(
        asset_id=channel.asset_id,
        canonical_key=channel.canonical_key,
        source_name=channel.source_name,
        receive_unit=channel.receive_unit,
        conversion=channel.conversion,
        interval_s=channel.interval_s,
        agg_semantics=channel.agg_semantics,
    )

    db.add(new_channel)
    db.commit()
    db.refresh(new_channel)

    return new_channel


@router.get(
    "",
    response_model=list[ChannelResponse],
)
def get_channels(
    db: Session = Depends(get_db),
):
    result = db.execute(
        select(Channel).order_by(Channel.source_name)
    )

    return result.scalars().all()


@router.get(
    "/{channel_id}",
    response_model=ChannelResponse,
)
def get_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    return channel
