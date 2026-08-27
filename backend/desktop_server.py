"""Standalone server entrypoint used by the packaged Vtubecord desktop app."""

from __future__ import annotations

import argparse
import os

import uvicorn

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Vtubecord local API server")
    parser.add_argument("--host", default=os.environ.get("VTUBECORD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VTUBECORD_PORT", "8000")))
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
