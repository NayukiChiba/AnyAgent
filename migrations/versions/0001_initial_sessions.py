"""初始迁移：会话快照表

Revision ID: 0001
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 与 anyagent.infrastructure.sqlite.models.SessionRecord 保持一致；
    # 后续 schema 变更必须新增迁移脚本，不得修改本文件
    op.create_table(
        "anyagent_chat_sessions",
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("session_id"),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("anyagent_chat_sessions")
