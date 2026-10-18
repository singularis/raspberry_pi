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
from fetch import dish_count, mint, should_gpu_on, throttled_flags
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
    assert gpu_state(True, True, False, True, True, 40, "off") == "ok"
    assert gpu_state(True, True, False, True, True, 40, "starting") == "ok"
    assert gpu_state(True, True, True, False, False, 40) == "warn"
    assert pi_state(47, 40, 40, False, False) == "ok"
    assert pi_state(None, None, None, False, False) == "stale"
    assert node_state(True, None, None, None, None) == "stale"
    assert pi_state(47, 20, 40, True, False) == "crit"
    assert pi_state(47, 70, 40, False, False) == "crit"
    assert pi_state(47, 69, 40, False, False) == "ok"
    assert eater_state(False, True) == "crit"
    assert eater_state(True, False) == "crit"
    assert eater_state(True, True) == "ok"
    assert backup_state(False, False, False, False, False, False) == "crit"
    assert backup_state(True, False, False, False, False, True) == "busy"
    assert backup_state(True, True, False, False, False, False) == "warn"
    assert backup_state(True, False, False, False, False, False, esp_down=True) == "crit"
    assert backup_state(False, False, False, False, False, False, archive_only=True) == "warn"
    assert backup_state(True, False, False, False, False, True, stuck=True) == "ok"
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


def test_detail_pages():
    tiles = build({
        "nodes": {
            "racoon": {"cpu": 12, "ram_pct": 37, "temp": 61, "disks": [
                {"name": "root", "pct": 40, "free_gb": 200},
                {"name": "other_hdd", "pct": 55, "free_gb": 800},
            ]},
            "worker": {"cpu": 20, "free_gb": 2.0, "temp": 41, "ready": True},
        },
        "pi": {"temp": 47, "ram_free": 241, "sd_pct": 40, "wifi": -20},
        "eater": {"prod_ok": True, "dev_ok": True, "health_ok": True, "dishes": 2, "users_today": 0, "scans_today": 8},
        "net": {"router": True, "dns": True, "internet": True, "google_ms": 18, "dns_ms": 4, "rssi": -20},
    })
    by = {t["id"]: t for t in tiles}
    names = [r[0] for r in by["racoon"]["pages"][0]["rows"]]
    assert names[0] == "cpu"
    assert names[1] == "ram free"
    assert "/ free" in names and "hdd free" in names
    assert names[-1] == "k8s"
    assert by["racoon"]["cap"] == "cpu"
    assert by["worker"]["pages"][0]["rows"][-1][0] == "k8s"
    assert by["pi"]["pages"][0]["rows"][0][0] == "cpu"
    assert by["pi"]["pages"][0]["rows"][1][0] == "ram free"
    eat_rows = by["eateria"]["pages"][0]["rows"]
    assert eat_rows[0][0] == "scans"
    assert eat_rows[1][0] == "users"
    assert eat_rows[-1] == ["dev", "up", "ok"]
    assert by["eateria"]["big"] == "8"
    assert by["eateria"]["state"] == "ok"
    gpu_rows = by["gpu"]["pages"][0]["rows"]
    assert len(gpu_rows) == 9
    assert all(r[2] == "off" for r in gpu_rows)
    assert "actions" not in by["gpu"]["pages"][0]
    assert by["backup"]["pages"][0]["actions"][0]["id"] == "wake"
    assert by["backup"]["pages"][0]["actions"][1]["id"] == "backup"
    assert by["backup"]["pages"][0]["rows"][0] == ["staging free", "off", "off"]
    assert by["network"]["pages"][0]["rows"][0][0] == "ping"
    assert by["network"]["pages"][0]["rows"][2][0] == "pihole"
    assert by["network"]["big"].endswith("ms")


NODE_SAMPLE = """# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.
# TYPE node_cpu_seconds_total counter
node_cpu_seconds_total{cpu="0",mode="idle"} 100
node_cpu_seconds_total{cpu="0",mode="user"} 50
node_cpu_seconds_total{cpu="1",mode="idle"} 100
node_cpu_seconds_total{cpu="1",mode="user"} 50
node_cpu_guest_seconds_total{cpu="0",mode="user"} 999
node_memory_MemAvailable_bytes 4.294967296e+09
node_memory_MemTotal_bytes 1.7179869184e+10
node_filesystem_avail_bytes{device="/dev/nvme0n1p2",fstype="ext4",mountpoint="/"} 2.147483648e+11
node_filesystem_size_bytes{device="/dev/nvme0n1p2",fstype="ext4",mountpoint="/"} 4.294967296e+11
node_filesystem_avail_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/other_hdd"} 1e+12
node_filesystem_size_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/other_hdd"} 2e+12
node_filesystem_avail_bytes{device="/dev/nvme0n1p1",fstype="vfat",mountpoint="/boot/efi"} 5e+08
node_filesystem_size_bytes{device="/dev/nvme0n1p1",fstype="vfat",mountpoint="/boot/efi"} 5.36870912e+08
node_filesystem_size_bytes{device="tmpfs",fstype="tmpfs",mountpoint="/run"} 1e+09
node_hwmon_temp_celsius{chip="platform_coretemp_0",sensor="temp1"} 61
node_hwmon_temp_celsius{chip="platform_coretemp_0",sensor="temp2"} 70
node_hwmon_temp_celsius{chip="nvme_nvme0",sensor="temp1"} 45
"""


def test_node_exporter(monkeypatch):
    import fetch
    assert fetch.scrape(None) == {}
    fetch._node_cpu.clear()
    text = {"body": NODE_SAMPLE}
    monkeypatch.setattr(fetch, "scrape", lambda ip, timeout=3: fetch.parse_metrics(text["body"]))
    first = fetch.node_metrics("racoon", "192.0.2.1")
    assert first["cpu"] is None
    assert round(first["ram_pct"]) == 75
    assert round(first["free_gb"]) == 4
    assert round(first["disk_pct"]) == 50
    assert first["temp"] == 61
    assert [d["name"] for d in first["disks"]] == ["other_hdd", "root", "boot-efi"]
    text["body"] = NODE_SAMPLE.replace('mode="idle"} 100', 'mode="idle"} 130').replace('mode="user"} 50', 'mode="user"} 60')
    assert round(fetch.node_metrics("racoon", "192.0.2.1")["cpu"]) == 25


def test_protobuf_dish_count():
    assert dish_count(b"\x0a\x00\x0a\x00") == 2


def test_room_sensor():
    tiles = build({
        "pi": {
            "temp": 57,
            "ram_free": 200,
            "ram_mb": 428,
            "sd_pct": 40,
            "sensor": {"temp": 26.8, "hum": 37.8, "press": 1028.6},
        },
    })
    pi = {t["id"]: t for t in tiles}["pi"]
    assert pi["big"] == "57C"
    assert pi["cap"] == "soc"
    assert pi["state"] == "ok"
    assert [r[0] for r in pi["pages"][0]["rows"]] == ["soc", "cpu", "ram free", "sd free", "humid", "hPa", "temp", "power"]
    rows = {r[0]: r for r in pi["pages"][0]["rows"]}
    assert rows["temp"] == ["temp", "27C", "ok"]
    assert rows["humid"][1] == "38%"
    assert rows["hPa"] == ["hPa", "1029", "ok"]
    assert rows["soc"] == ["soc", "57C", "ok"]
    body = snap(
        tiles,
        weather={"temp": 16, "hum": 80, "press": 1016},
        sensor={"temp": 26.8, "hum": 37.8, "press": 1028.6},
    )
    assert body["temp_out"] == "16°C"
    assert body["temp_in"] == "27°C"
    assert body["humidity"] == "80%"
    assert body["sensor"] == {"temp": "27°C", "humidity": "38%", "pressure": "1029"}
    plain = {t["id"]: t for t in build({"pi": {"temp": 47, "ram_free": 241, "sd_pct": 40}})}["pi"]
    assert plain["cap"] == "cpu temp"
    assert plain["big"] == "47C"
    assert "humid" not in {r[0] for r in plain["pages"][0]["rows"]}


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
    page = c.get("/")
    assert page.status_code == 200
    assert "LCD monitor" in page.text
    css = c.get("/static/style.css")
    assert css.status_code == 200
    assert "--ok" in css.text
    denied = c.post("/api/actions", json={"id": "wake"})
    assert denied.status_code == 403
    ok = c.post("/api/actions", json={"id": "backup"}, headers={"X-Forwarded-For": "ignored"})
    # TestClient host is testclient, not allowed
    assert ok.status_code == 403
