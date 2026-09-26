import jwt

from checks import (
    backup_state,
    build,
    claw_lines,
    eater_state,
    gpu_state,
    net_state,
    node_state,
    pi_state,
)
from fetch import mint, should_gpu_on, throttled_flags
from model import snap
from datetime import datetime
from zoneinfo import ZoneInfo


def test_states():
    assert node_state(False, 1, 1, 1, 40) == "crit"
    assert node_state(True, 10, 50, 50, 40, free_gb=0.5) == "crit"
    assert node_state(True, 10, 50, 50, 40, free_gb=0.9) == "warn"
    assert node_state(True, 90, 50, 50, 40) == "warn"
    assert gpu_state(False, False, False, False, None, None) == "off"
    assert gpu_state(False, True, False, True, None, None) == "off"
    assert gpu_state(True, True, False, True, True, 40) == "crit"
    assert gpu_state(True, True, True, False, False, 40) == "warn"
    assert pi_state(47, 174, 40, False, False) == "ok"
    assert pi_state(47, 20, 40, True, False) == "crit"
    assert eater_state(False, 10, True, True, False, False) == "crit"
    assert eater_state(True, 1500, False, True, False, False) == "warn"
    assert backup_state(False, False, False, False, False, False) == "crit"
    assert backup_state(True, False, False, False, False, True) == "busy"
    assert backup_state(True, True, False, False, False, False) == "warn"
    assert net_state(False, True, 0, 10, 10, -50) == "crit"
    assert net_state(True, True, 0, 90, 10, -50) == "warn"


def test_claw_never_crit():
    lines, ok = claw_lines({"ok": True, "plugins": {"errors": []}, "channels": {"telegram": {"connected": True}}}, {"tasks": {"failures": 0}, "taskAudit": {"errors": 0}})
    assert ok
    assert any("gateway ok" in x for x in lines)
    lines, ok = claw_lines({"ok": False, "plugins": {"errors": ["x"]}}, None)
    assert ok is False
    tiles = build({"gpu": {"on": True, "should_on": True, "vllm": True, "claw_ok": False, "claw_lines": lines, "temp": 40}})
    gpu = next(t for t in tiles if t["id"] == "gpu")
    assert gpu["state"] == "warn"


def test_snap_and_jwt():
    tiles = build({})
    assert len(tiles) == 8
    body = snap(tiles)
    assert body["schema"] == 1
    token = mint("secret")
    claims = jwt.decode(token, "secret", algorithms=["HS256"])
    assert claims["sub"] == "singularis314@gmail.com"
    assert claims["exp"] - claims["iat"] == 300
    assert should_gpu_on(datetime(2026, 9, 26, 15, 0, tzinfo=ZoneInfo("Europe/London")))
    assert not should_gpu_on(datetime(2026, 9, 26, 23, 30, tzinfo=ZoneInfo("Europe/London")))
    now, boot = throttled_flags("0x50000")
    assert now is False and boot is True
    now, boot = throttled_flags("0x1")
    assert now is True


def test_actions_allow(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    monkeypatch.setenv("COLLECTOR_LOOP", "0")
    appmod._cache["snap"] = snap(build({}))
    c = TestClient(appmod.app)
    denied = c.post("/api/actions", json={"id": "wake"})
    assert denied.status_code == 403
    ok = c.post("/api/actions", json={"id": "backup"}, headers={"X-Forwarded-For": "ignored"})
    # TestClient host is testclient, not allowed
    assert ok.status_code == 403
