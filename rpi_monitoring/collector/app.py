"""LCD collector. The Pi only GETs /api/display."""

import os
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from checks import build
from fetch import assemble, fire
from model import snap

app = FastAPI()
_lock = threading.Lock()
_cache = {"snap": None, "leader": True}
ALLOW = {"192.168.0.89", "192.168.0.10", "127.0.0.1"}
WEB = os.path.join(os.path.dirname(__file__), "web")


def leader():
    return bool(_cache.get("leader", True))


def refresh():
    if not leader():
        return
    try:
        facts = assemble()
        built = snap(build(facts), temp_out=facts.get("temp_out"))
    except Exception as exc:
        built = _cache.get("snap")
        print("refresh failed", type(exc).__name__)
    with _lock:
        if built is not None:
            _cache["snap"] = built
    if built is not None and leader():
        try:
            from lease import publish
            publish(built)
        except Exception as exc:
            print("publish failed", type(exc).__name__)


def _remember(body):
    if body is None:
        return
    with _lock:
        _cache["snap"] = body


def _loop():
    while True:
        try:
            from lease import hold, load
            _cache["leader"] = hold()
            if not _cache["leader"]:
                _remember(load())
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
    with _lock:
        ok = _cache.get("snap") is not None
    if not ok:
        try:
            from lease import load
            _remember(load())
        except Exception:
            pass
        with _lock:
            ok = _cache.get("snap") is not None
    if not ok:
        return JSONResponse({"ready": False}, status_code=503)
    return {"ready": True, "leader": leader()}


def _lan(host):
    parts = (host or "").split(".")
    return len(parts) == 4 and parts[0] == "192" and parts[1] == "168" and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/api/display")
def display():
    with _lock:
        body = _cache.get("snap")
    if body is None:
        try:
            from lease import load
            _remember(load())
        except Exception:
            pass
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
    if host not in ALLOW and not _lan(host):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await request.json()
    action = body.get("id")
    if action not in ("wake", "backup"):
        return JSONResponse({"error": "unknown"}, status_code=400)
    threading.Thread(target=fire, args=(action,), daemon=True).start()
    return {"ok": True, "id": action}
