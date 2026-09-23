"""SQLAlchemy models for Organization, User, Plant, Asset, CanonicalSignal, and Channel."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, generate_uuid


class Organization(Base, TimestampMixin):
    """Multi-tenant Organization entity."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    users: Mapped[List[User]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    plants: Mapped[List[Plant]] = relationship(
        "Plant", back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base, TimestampMixin):
    """User accounts belonging to an Organization."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organization: Mapped[Organization] = relationship("Organization", back_populates="users")


class Plant(Base, TimestampMixin):
    """Solar or Wind Power Plant."""

    __tablename__ = "plants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    plant_type: Mapped[str] = mapped_column(String(32), default="solar", nullable=False)
    capacity_dc_kwp: Mapped[float] = mapped_column(Float, nullable=False)
    capacity_ac_kw: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    tariff_inr_per_kwh: Mapped[float] = mapped_column(Float, default=3.50, nullable=False)
    expected_pr: Mapped[float] = mapped_column(Float, default=0.78, nullable=False)
    cod_date: Mapped[date] = mapped_column(Date, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_plant_org_name"),
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="plants")
    assets: Mapped[List[Asset]] = relationship(
        "Asset", back_populates="plant", cascade="all, delete-orphan"
    )


class Asset(Base, TimestampMixin):
    """Hierarchical Asset entity (Block, Inverter, Weather Station, String)."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    plant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("plant_id", "name", name="uq_asset_plant_name"),
    )

    plant: Mapped[Plant] = relationship("Plant", back_populates="assets")
    parent: Mapped[Optional[Asset]] = relationship(
        "Asset", remote_side=[id], back_populates="children"
    )
    children: Mapped[List[Asset]] = relationship(
        "Asset", back_populates="parent", cascade="all, delete-orphan"
    )
    channels: Mapped[List[Channel]] = relationship(
        "Channel", back_populates="asset", cascade="all, delete-orphan"
    )


class CanonicalSignal(Base, TimestampMixin):
    """Standardized Canonical Telemetry Dictionary Signal."""

    __tablename__ = "canonical_signals"

    signal_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    data_type: Mapped[str] = mapped_column(String(32), default="float", nullable=False)
    monotonicity: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    bound_min_rule: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    bound_max_rule: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    channels: Mapped[List[Channel]] = relationship(
        "Channel", back_populates="canonical_signal"
    )


class Channel(Base, TimestampMixin):
    """Configured ingestion channel binding an Asset to a CanonicalSignal."""

    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_signal_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("canonical_signals.signal_key", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    interval_s: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    aggregation_method: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("asset_id", "canonical_signal_key", name="uq_channel_asset_signal"),
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="channels")
    canonical_signal: Mapped[CanonicalSignal] = relationship(
        "CanonicalSignal", back_populates="channels"
    )
    observations: Mapped[List[Observation]] = relationship(
        "Observation", back_populates="channel", cascade="all, delete-orphan"
    )


class Observation(Base, TimestampMixin):
    """Time-series telemetry observation record mapped to a Channel."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    raw_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qc_flag: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("channel_id", "timestamp", name="uq_observation_channel_timestamp"),
    )

    channel: Mapped[Channel] = relationship("Channel", back_populates="observations")
