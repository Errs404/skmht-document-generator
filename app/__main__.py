"""Titik masuk aplikasi: ``python -m app`` atau ``python run.py``."""

from __future__ import annotations

import argparse

from .server import DEFAULT_PORT, HOST, serve


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generator SKMHT lokal (offline).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port server lokal (default {DEFAULT_PORT}).")
    args = parser.parse_args()
    serve(port=args.port)


if __name__ == "__main__":
    main()
