import argparse
from pathlib import Path

import uvicorn

from anyagent.bootstrap import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the AnyAgent API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    data_dir = Path(__file__).resolve().parent / "data"
    uvicorn.run(create_app(data_dir), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
