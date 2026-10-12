"""Production entry point: the web app and the API from one origin.

The API keeps its own routes unchanged and is mounted under /api -- the same
prefix the Vite dev/preview proxy strips locally -- and every other path is
the built single-page app (web/dist), with index.html for client-side routes.

    uvicorn app.serve:app
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import app as api

WEB_DIST = Path(
    os.environ.get("RUNSENSE_WEB_DIST")
    or Path(__file__).resolve().parents[2] / "web" / "dist"
).resolve()

# files that must never be served stale after a redeploy
_NO_CACHE = {"index.html", "sw.js", "manifest.webmanifest"}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api)
if (WEB_DIST / "assets").is_dir():
    # content-hashed file names: safe to cache
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def web_app(path: str) -> FileResponse:
    index = WEB_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="web app not built")
    target = (WEB_DIST / path).resolve()
    if path and target.is_file() and WEB_DIST in target.parents:
        file = target
    else:
        file = index  # client-side route, e.g. /app/history
    headers = {"Cache-Control": "no-cache"} if file.name in _NO_CACHE else None
    return FileResponse(file, headers=headers)
