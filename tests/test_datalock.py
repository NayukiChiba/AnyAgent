"""data 目录进程互斥锁：占用拒绝、释放复用与实例幂等。"""

import pytest

from anyagent.runtime.datalock import DataDirectoryLock, DataLockError


def test_second_holder_is_rejected(tmp_path):
    lock_path = tmp_path / "data" / "anyagent.lock"
    first = DataDirectoryLock(lock_path)
    first.acquire()
    try:
        second = DataDirectoryLock(lock_path)
        with pytest.raises(DataLockError, match="另一个 AnyAgent 进程"):
            second.acquire()
    finally:
        first.release()


def test_lock_is_reusable_after_release(tmp_path):
    lock_path = tmp_path / "data" / "anyagent.lock"
    first = DataDirectoryLock(lock_path)
    first.acquire()
    first.release()
    second = DataDirectoryLock(lock_path)
    second.acquire()
    second.release()


def test_release_without_acquire_is_safe(tmp_path):
    DataDirectoryLock(tmp_path / "data" / "anyagent.lock").release()


def test_acquire_is_idempotent_within_one_instance(tmp_path):
    lock = DataDirectoryLock(tmp_path / "data" / "anyagent.lock")
    lock.acquire()
    lock.acquire()  # 重复获取复用同一把锁，不抛错
    lock.release()


def test_independent_data_directories_do_not_conflict(tmp_path):
    first = DataDirectoryLock(tmp_path / "a" / "anyagent.lock")
    second = DataDirectoryLock(tmp_path / "b" / "anyagent.lock")
    first.acquire()
    second.acquire()
    first.release()
    second.release()


def test_lock_file_is_left_behind_but_unlocked(tmp_path):
    """锁文件可以残留（内核级锁随 fd 释放），下一次启动不受影响。"""
    lock_path = tmp_path / "data" / "anyagent.lock"
    lock = DataDirectoryLock(lock_path)
    lock.acquire()
    lock.release()
    assert lock_path.exists()
    DataDirectoryLock(lock_path).acquire()
