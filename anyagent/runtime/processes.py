"""Manage subprocess cleanup owned by the AnyAgent runtime."""

import os

import psutil

from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


def terminate_child_processes(timeout_seconds: float = 3.0) -> None:
    """Terminate all descendant processes and kill survivors after a timeout.

    Args:
        timeout_seconds: Maximum time to wait after each termination phase.
    """
    try:
        children = psutil.Process(os.getpid()).children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        logger.warning("Unable to inspect child processes during shutdown: %s", error)
        return
    if not children:
        return

    logger.info("Terminating child processes: count=%d", len(children))
    pending = []
    for child in children:
        try:
            logger.info("Terminating child process: pid=%d", child.pid)
            child.terminate()
            pending.append(child)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            logger.warning("Unable to terminate child process %d: %s", child.pid, error)

    _, alive = psutil.wait_procs(pending, timeout=timeout_seconds)
    for child in alive:
        try:
            logger.warning("Killing unresponsive child process: pid=%d", child.pid)
            child.kill()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            logger.error("Unable to kill child process %d: %s", child.pid, error)
    psutil.wait_procs(alive, timeout=timeout_seconds)
