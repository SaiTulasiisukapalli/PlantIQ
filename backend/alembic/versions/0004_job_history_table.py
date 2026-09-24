"""Create job_history table for background pipeline benchmarks and ingestion tracking.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24 11:38:00.000000

Task: S2-AI-04
Description:
- Creates `job_history` table for persisting pipeline run history, anomaly QC summaries,
  and benchmark throughput performance.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create job_history table."""
    op.create_table(
        "job_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False, unique=True),
        sa.Column("job_type", sa.String(64), nullable=False, server_default="pipeline_benchmark"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("dataset_name", sa.String(255), nullable=True),
        sa.Column("dataset_path", sa.String(512), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("throughput_rows_per_sec", sa.Float(), nullable=True),
        sa.Column("qc_summary", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_history_run_id", "job_history", ["run_id"])
    op.create_index("ix_job_history_job_type", "job_history", ["job_type"])
    op.create_index("ix_job_history_status", "job_history", ["status"])


def downgrade() -> None:
    """Drop job_history table."""
    op.drop_index("ix_job_history_status", table_name="job_history")
    op.drop_index("ix_job_history_job_type", table_name="job_history")
    op.drop_index("ix_job_history_run_id", table_name="job_history")
    op.drop_table("job_history")
