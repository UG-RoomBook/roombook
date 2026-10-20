"""Serve the built React application from the same origin as the API."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException

# Vite fingerprints everything under assets/, so those files never change in place.
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


def install_frontend(application: FastAPI, static_dir: Path | None) -> None:
    """Add the single-page-app fallback after every API route.

    Call this last in create_app: routes match in registration order, so every
    API and operational route wins over the fallback. Unknown /api paths still
    return the JSON 404 envelope instead of the HTML shell.
    """
    if static_dir is None:
        return
    root = static_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"ROOMBOOK_STATIC_DIR has no index.html: {root}")

    @application.get("/{path:path}", include_in_schema=False, response_model=None)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            cache = IMMUTABLE if path.startswith("assets/") else REVALIDATE
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": REVALIDATE})
