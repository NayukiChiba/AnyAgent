"""数据库版本化迁移：编程式驱动 Alembic，失败时从备份恢复。

替代启动期的 create_all：
- 空库执行 upgrade 建表并记录版本；
- 存量库（有业务表但无 alembic_version，即 create_all 时代的数据）
  先 stamp 到初始版本再 upgrade，schema 不重复创建；
- 版本库执行增量 upgrade；版本已与 head 一致时直接返回，
  不备份、不执行迁移，避免每次启动都生成备份副本。

有待执行的迁移动作且数据库非空时，先备份（WAL checkpoint 后复制），
任何一步失败从备份恢复并向调用方抛错，保证迁移失败不破坏已有数据。
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from anyagent.configs import paths
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

# 初始迁移版本号：存量库（create_all 时期）的 schema 锚点
INITIAL_REVISION = "0001"


def _build_config(file_path: Path) -> Config:
    """构造编程式 Alembic 配置（无 alembic.ini），URL 经 attributes 传给 env.py。"""
    config = Config()
    config.set_main_option("script_location", str(paths.get_migrations_dir()))
    # 关闭 alembic 自身的日志配置加载，统一走项目日志链条
    config.set_main_option("configure_logger", "false")
    config.attributes["sqlalchemy.url"] = f"sqlite:///{file_path.as_posix()}"
    return config


def _inspect_state(file_path: Path) -> tuple[bool, str | None]:
    """返回（是否有业务表，当前迁移版本）；库不存在或无版本表时版本为 None。"""
    if not file_path.exists():
        return False, None
    engine = create_engine(f"sqlite:///{file_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
        has_user_tables = bool(tables - {"alembic_version"})
        current = None
        if "alembic_version" in tables:
            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).fetchone()
            current = row[0] if row else None
        return has_user_tables, current
    finally:
        engine.dispose()


def _backup_database(file_path: Path) -> Path:
    """把数据库备份到 data 内的时间戳副本；先合并 WAL，保证单文件完整。"""
    with sqlite3.connect(file_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    backup = paths.get_database_backup_path(file_path, time.time_ns())
    shutil.copy2(file_path, backup)
    logger.info("迁移前已备份数据库: %s", backup.name)
    return backup


def _restore_backup(backup: Path, file_path: Path) -> None:
    """从备份恢复数据库，并清理可能残留的 WAL/SHM 文件。"""
    shutil.copy2(backup, file_path)
    for suffix in ("-wal", "-shm"):
        residue = file_path.with_name(file_path.name + suffix)
        residue.unlink(missing_ok=True)


def migrate_database(file_path: Path) -> None:
    """把数据库迁移到最新版本。

    版本已与 head 一致时直接返回（不备份、不执行迁移）；只有存在
    实际迁移动作（存量库补登版本或版本落后）且数据库非空时才备份。

    Args:
        file_path: 已校验的 SQLite 数据库绝对路径。

    Raises:
        Exception: 迁移失败；非空库已从备份恢复到迁移前状态。
    """
    has_user_tables, current = _inspect_state(file_path)
    config = _build_config(file_path)
    head = ScriptDirectory.from_config(config).get_current_head()
    # 存量库（有业务表、无版本记录）需要先 stamp 补登版本
    needs_stamp = has_user_tables and current is None
    if not needs_stamp and current == head:
        logger.info("数据库表结构已是最新: %s", file_path.name)
        return
    backup = None
    # 只对已有数据的库做备份；空库升级失败直接删除文件即可
    if file_path.exists() and file_path.stat().st_size > 0:
        backup = _backup_database(file_path)
    try:
        if needs_stamp:
            # 接管 create_all 时代的存量库：schema 已与初始迁移一致，只登记版本
            command.stamp(config, INITIAL_REVISION)
            logger.info(
                "存量数据库已登记到版本 %s（表结构不变）",
                INITIAL_REVISION,
            )
        command.upgrade(config, "head")
    except Exception:
        logger.exception("数据库迁移失败: %s", file_path.name)
        if backup is not None:
            _restore_backup(backup, file_path)
            logger.warning("已从备份恢复数据库: %s", backup.name)
        elif file_path.exists():
            # 空库升级失败不留半成品
            file_path.unlink()
        raise
    logger.info("数据库迁移完成: %s（当前版本 %s）", file_path.name, head)
