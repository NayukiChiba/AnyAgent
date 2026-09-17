import argparse

import uvicorn

from anyagent.bootstrap import create_app
from anyagent.configs import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the AnyAgent API server.")
    parser.add_argument(
        "--config", help="Configuration file relative to the project root."
    )
    parser.add_argument("--host", help="Override the configured server host.")
    parser.add_argument("--port", type=int, help="Override the configured server port.")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config, host=args.host, port=args.port)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    uvicorn.run(
        create_app(settings.paths.data_dir),
        host=settings.server.host,
        port=settings.server.port,
    )


if __name__ == "__main__":
    main()
