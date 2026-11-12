"""ASGI entrypoint: uvicorn backend.main:app --reload."""

from __future__ import annotations

from backend.app import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8787, reload=False)
