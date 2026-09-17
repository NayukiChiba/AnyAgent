import argparse

import uvicorn

from anyagent.bootstrap import create_app
from anyagent.logger import LogManager, logger
from configs import ServerSettings, config


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

    LogManager.configure(config.logging)
    try:
        logger.info("Starting AnyAgent on %s:%s", server.host, server.port)
        uvicorn.run(
            create_app(),
            host=server.host,
            port=server.port,
            log_config=None,
            log_level=config.logging.level.lower(),
        )
    except Exception:
        logger.exception("Server execution failed")
        raise
    finally:
        logger.info("AnyAgent stopped")
        LogManager.shutdown()


if __name__ == "__main__":
    main()
