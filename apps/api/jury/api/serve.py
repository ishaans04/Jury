"""Local API launcher: `uv run python -m jury.api.serve [--host H] [--port P]`.

Why not plain `uvicorn jury.api.main:app`: on Windows, uvicorn runs the app
on a `ProactorEventLoop` unless it spawns a reload/worker subprocess, and
psycopg's async driver cannot run on a `ProactorEventLoop` -- every database
connection fails. `--reload` only works there by accident (its worker gets a
`SelectorEventLoop`) and leaves orphaned workers bound to the port when the
reloader is killed. This launcher pins a `SelectorEventLoop`, so a plain
single process works on every OS. The container deploy (Linux) is unaffected.
"""
import argparse
import asyncio

import uvicorn


def loop_factory() -> type[asyncio.AbstractEventLoop]:
    return asyncio.SelectorEventLoop


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run The Jury API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server = uvicorn.Server(uvicorn.Config("jury.api.main:app", host=args.host, port=args.port))
    asyncio.run(server.serve(), loop_factory=loop_factory())


if __name__ == "__main__":
    main()
