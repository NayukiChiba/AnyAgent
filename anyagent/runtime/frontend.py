"""Prepare frontend build artifacts for source-based application startup."""

import shutil
import subprocess

from anyagent.configs import paths
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


def ensure_frontend_build() -> bool:
    """Build the Vue frontend when its entrypoint is missing.

    Returns:
        True when a usable frontend entrypoint exists, otherwise False. Build
        failures are reported but do not prevent the backend from starting.
    """
    index_path = paths.get_frontend_index_path()
    if index_path.is_file():
        return True

    frontend_dir = paths.get_frontend_dir()
    package_path = paths.get_frontend_package_path()
    lock_path = paths.get_frontend_lock_path()
    if not package_path.is_file() or not lock_path.is_file():
        logger.error(
            "Frontend build skipped: package.json or package-lock.json is missing in %s",
            frontend_dir,
        )
        return False

    npm_command = shutil.which("npm")
    if npm_command is None:
        logger.error(
            "Frontend build skipped: npm was not found; install Node.js 22 or newer"
        )
        return False

    try:
        if not paths.get_frontend_node_modules_dir().is_dir():
            logger.info("Installing frontend dependencies with npm ci")
            subprocess.run(
                [npm_command, "ci"],
                cwd=frontend_dir,
                check=True,
            )
        logger.info("Building frontend with npm run build")
        subprocess.run(
            [npm_command, "run", "build"],
            cwd=frontend_dir,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        logger.error("Automatic frontend build failed: %s", error)
        return False

    if not index_path.is_file():
        logger.error(
            "Automatic frontend build finished without creating %s", index_path
        )
        return False

    logger.info("Frontend build completed: %s", index_path)
    return True
