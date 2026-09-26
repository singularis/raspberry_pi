"""LCD collector. The Pi only GETs /api/display."""

import os
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from checks import build
from fetch import assemble, fire
from model import snap

app = FastAPI()
_lock = threading.Lock()
_cache = {"snap": None, "leader": True}
ALLOW = {"192.168.0.89", "192.168.0.10", "127.0.0.1"}


def leader():
    return bool(_cache.get("leader", True))


def refresh():
    if not leader():
        return
    try:
        built = snap(build(assemble()))
    except Exception as exc:
        built = _cache.get("snap")
        print("refresh failed", type(exc).__name__)
    with _lock:
        if built is not None:
            _cache["snap"] = built


def _loop():
    while True:
        try:
            from lease import hold
            _cache["leader"] = hold()
        except Exception:
            _cache["leader"] = True
        if _cache["leader"]:
            refresh()
        time.sleep(int(os.environ.get("REFRESH_S", "60")))


@app.on_event("startup")
def startup():
    if os.environ.get("COLLECTOR_LOOP", "1") == "1":
        threading.Thread(target=_loop, daemon=True).start()


@app.get("/ready")
def ready():
    if not leader():
        return JSONResponse({"leader": False}, status_code=503)
    return {"leader": True}


@app.get("/api/display")
def display():
    with _lock:
        body = _cache.get("snap")
    if body is None and leader():
        refresh()
        with _lock:
            body = _cache.get("snap")
    if body is None:
        return JSONResponse({"schema": 1, "tiles": [], "summary": {"warn": 0, "crit": 0, "worst": ""}}, status_code=503)
    return body


@app.post("/api/actions")
async def actions(request: Request):
    host = request.client.host if request.client else ""
    if host not in ALLOW:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await request.json()
    action = body.get("id")
    if action not in ("wake", "backup"):
        return JSONResponse({"error": "unknown"}, status_code=400)
    threading.Thread(target=fire, args=(action,), daemon=True).start()
    return {"ok": True, "id": action}
