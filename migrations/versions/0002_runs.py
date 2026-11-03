"""新增 anyagent_runs 表（M1 Run 持久化）

Revision ID: 0002
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 与 anyagent.infrastructure.sqlite.models.RunRecord 保持一致；
    # 后续 schema 变更必须新增迁移脚本，不得修改本文件
    op.create_table(
        "anyagent_runs",
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("finished_at", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_anyagent_runs_session_id", "anyagent_runs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_anyagent_runs_session_id", table_name="anyagent_runs")
    op.drop_table("anyagent_runs")
