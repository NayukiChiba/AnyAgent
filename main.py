import argparse
import os
import sys

import uvicorn

from anyagent.configs import (
    ServerSettings,
    config,
    load_langchain_config,
    logging_config,
    paths,
)
from anyagent.runtime.bootstrap import create_app
from anyagent.runtime.restart import RestartController
from anyagent.utils.logger import LogManager, logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the AnyAgent API server.")
    parser.add_argument("--host", help="Override the configured server host.")
    parser.add_argument("--port", type=int, help="Override the configured server port.")
    args = parser.parse_args()
    try:
        server = ServerSettings(
            host=args.host if args.host is not None else config.server.host,
            port=args.port if args.port is not None else config.server.port,
        )
    except ValueError as error:
        parser.error(str(error))

    def stop_server() -> None:
        http_server.should_exit = True

    restart = RestartController(
        stop_server,
        port_override=args.port,
        host_override=args.host,
        current_host=server.host,
        current_port=server.port,
    )
    settings = load_langchain_config()
    http_server = uvicorn.Server(
        uvicorn.Config(
            create_app(agent_settings=settings, restart_controller=restart),
            host=server.host,
            port=server.port,
            log_config=None,
            log_level=logging_config.level.lower(),
            timeout_graceful_shutdown=settings.cleanup_timeout_seconds,
        )
    )
    LogManager.configure(logging_config)
    try:
        logger.info("Starting AnyAgent on %s:%s", server.host, server.port)
        http_server.run()
    except KeyboardInterrupt:
        restart.requested = False
    except Exception:
        logger.exception("Server execution failed")
        raise
    finally:
        logger.info("AnyAgent stopped")
        LogManager.shutdown()

    if restart.requested:
        os.execv(
            sys.executable, [sys.executable, str(paths.get_main_path()), *sys.argv[1:]]
        )


if __name__ == "__main__":
    main()
