"""Network checks. Each call is best-effort and returns a fact dict."""

import os
import socket
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import jwt

PROM = os.environ.get("PROM_URL", "http://prometheus.lens-metrics.svc:80")
BACKEPR = os.environ.get("BACKEPR_URL", "http://192.168.0.122:8000")
PI = os.environ.get("PI_HEALTH_URL", "http://192.168.0.89:8080/health")
VLLM = os.environ.get("VLLM_URL", "http://192.168.0.160:8000/health")
EATER_PROD = os.environ.get("EATER_PROD_URL", "https://chater.singularis.work/eater_get_today")
EATER_DEV = os.environ.get("EATER_DEV_URL", "https://chater.singularis.work/dev/eater_get_today")
EATER_PROD_HOP = os.environ.get("EATER_PROD_HOP", "http://chater-ui.chater-ui.svc.cluster.local:5000/eater_get_today")
EATER_DEV_HOP = os.environ.get("EATER_DEV_HOP", "http://chater-ui-dev.chater-ui-dev.svc.cluster.local:5000/eater_get_today")
HEALTHZ = os.environ.get("EATER_HEALTHZ", "https://chater.singularis.work/healthz")
SYNTH_EMAIL = "singularis314@gmail.com"
UA = "lcd-synthetic"


def prom(query, timeout=4):
    try:
        r = httpx.get(PROM + "/api/v1/query", params={"query": query}, timeout=timeout)
        r.raise_for_status()
        data = r.json()["data"]["result"]
        return data
    except Exception:
        return []


def _series(node, query):
    rows = prom(query)
    for row in rows:
        if row.get("metric", {}).get("kubernetes_node") == node:
            try:
                return float(row["value"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                return None
    return None


def node_metrics(node):
    cpu = _series(node, f'100 - (avg(rate(node_cpu_seconds_total{{mode="idle",kubernetes_node="{node}"}}[5m])) * 100)')
    avail = _series(node, f'node_memory_MemAvailable_bytes{{kubernetes_node="{node}"}}')
    total = _series(node, f'node_memory_MemTotal_bytes{{kubernetes_node="{node}"}}')
    disk_avail = _series(node, f'node_filesystem_avail_bytes{{kubernetes_node="{node}",mountpoint="/",fstype!="tmpfs"}}')
    disk_size = _series(node, f'node_filesystem_size_bytes{{kubernetes_node="{node}",mountpoint="/",fstype!="tmpfs"}}')
    temp = _series(node, f'max(node_hwmon_temp_celsius{{kubernetes_node="{node}"}})')
    ram_pct = (100 * (1 - avail / total)) if avail and total else None
    disk_pct = (100 * (1 - disk_avail / disk_size)) if disk_avail and disk_size else None
    free_gb = (avail / (1024 ** 3)) if avail else None
    return {"cpu": cpu, "ram_pct": ram_pct, "disk_pct": disk_pct, "temp": temp, "free_gb": free_gb, "ready": True}


def k8s_ready():
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return {}
    try:
        token = open(token_path).read()
        r = httpx.get(
            "https://kubernetes.default.svc/api/v1/nodes",
            headers={"Authorization": "Bearer " + token},
            verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            timeout=4,
        )
        r.raise_for_status()
        out = {}
        for item in r.json().get("items", []):
            name = item["metadata"]["name"]
            ready = False
            for cond in item.get("status", {}).get("conditions", []):
                if cond.get("type") == "Ready":
                    ready = cond.get("status") == "True"
                if cond.get("type") == "MemoryPressure" and cond.get("status") == "True" and name == "racoon-worker":
                    out.setdefault(name, {})["pressure"] = True
            out.setdefault(name, {})["ready"] = ready
        return out
    except Exception:
        return {}


def backepr():
    out = {}
    try:
        nodes = httpx.get(BACKEPR + "/api/health/nodes", timeout=4).json()
        for n in nodes:
            out[n.get("name")] = n
    except Exception:
        pass
    dash = {}
    try:
        dash = httpx.get(BACKEPR + "/api/dashboard", timeout=4).json()
    except Exception:
        pass
    state = {}
    try:
        state = httpx.get(BACKEPR + "/api/actions/state", timeout=4).json()
    except Exception:
        pass
    return out, dash, state


def pi_health():
    try:
        return httpx.get(PI, timeout=4).json()
    except Exception:
        return {}


def vllm_up():
    try:
        r = httpx.get(VLLM, timeout=3)
        return r.status_code < 500
    except Exception:
        return False


def _secret(ns, name):
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        val = os.environ.get("JWT_SECRET_" + ns.replace("-", "_").upper())
        return val
    try:
        token = open(token_path).read()
        r = httpx.get(
            f"https://kubernetes.default.svc/api/v1/namespaces/{ns}/secrets/{name}",
            headers={"Authorization": "Bearer " + token},
            verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            timeout=4,
        )
        r.raise_for_status()
        import base64
        raw = r.json()["data"].get("JWT_SECRET")
        return base64.b64decode(raw).decode() if raw else None
    except Exception:
        return None


def mint(secret):
    now = int(time.time())
    return jwt.encode(
        {"sub": SYNTH_EMAIL, "iat": now, "exp": now + 300, "name": "lcd-synthetic", "picture": ""},
        secret,
        algorithm="HS256",
    )


def _get_eater(url, token):
    t0 = time.monotonic()
    r = httpx.get(url, headers={"Authorization": "Bearer " + token, "User-Agent": UA}, timeout=8)
    ms = int((time.monotonic() - t0) * 1000)
    dishes = None
    if r.status_code == 200:
        body = r.json()
        if isinstance(body, list):
            dishes = len(body)
        elif isinstance(body, dict):
            dishes = body.get("count") or len(body.get("dishes") or body.get("items") or [])
    return r.status_code == 200, ms, dishes


def eater():
    prod_secret = _secret("chater-ui", "chater-ui")
    dev_secret = _secret("chater-ui-dev", "chater-ui-dev")
    out = {"prod_ok": False, "dev_ok": False, "health_ok": False, "prod_ms": None, "dishes": None, "hop": ""}
    try:
        hr = httpx.get(HEALTHZ, timeout=4)
        out["health_ok"] = hr.status_code < 500
    except Exception:
        out["health_ok"] = False
    if prod_secret:
        try:
            ok, ms, dishes = _get_eater(EATER_PROD, mint(prod_secret))
            out.update(prod_ok=ok, prod_ms=ms, dishes=dishes, hop="public")
            if not ok:
                ok2, ms2, dishes2 = _get_eater(EATER_PROD_HOP, mint(prod_secret))
                out.update(prod_ok=ok2, prod_ms=ms2, dishes=dishes2, hop="chater-ui.chater-ui:5000")
        except Exception:
            try:
                ok2, ms2, dishes2 = _get_eater(EATER_PROD_HOP, mint(prod_secret))
                out.update(prod_ok=ok2, prod_ms=ms2, dishes=dishes2, hop="chater-ui.chater-ui:5000")
            except Exception:
                out["hop"] = "chater-ui.chater-ui:5000 failed"
    if dev_secret:
        try:
            ok, _, _ = _get_eater(EATER_DEV, mint(dev_secret))
            out["dev_ok"] = ok
            if not ok:
                ok2, _, _ = _get_eater(EATER_DEV_HOP, mint(dev_secret))
                out["dev_ok"] = ok2
                out["hop"] = (out["hop"] + " dev:chater-ui-dev").strip()
        except Exception:
            try:
                ok2, _, _ = _get_eater(EATER_DEV_HOP, mint(dev_secret))
                out["dev_ok"] = ok2
                out["hop"] = (out["hop"] + " dev:chater-ui-dev").strip()
            except Exception:
                out["dev_ok"] = False
    return out


def ping_ms(host, timeout=1):
    t0 = time.monotonic()
    try:
        socket.create_connection((host, 53 if host.endswith("91") or host.endswith("92") else 80), timeout).close()
        return int((time.monotonic() - t0) * 1000), True
    except Exception:
        return None, False


def should_gpu_on(now=None):
    now = now or datetime.now(ZoneInfo("Europe/London"))
    return 8 <= now.hour < 23


def throttled_flags(raw):
    try:
        n = int(str(raw), 16) if str(raw).startswith("0x") or any(c in str(raw).lower() for c in "abcdef") else int(str(raw))
    except (TypeError, ValueError):
        return False, False
    # bit 0 undervoltage now, bit 16 undervoltage since boot
    return bool(n & 1), bool(n & (1 << 16))


def assemble():
    ready = k8s_ready()
    rac = node_metrics("racoon")
    wrk = node_metrics("racoon-worker")
    gpu_m = node_metrics("racoon-gpu")
    nodes, dash, state = backepr()
    for key, src in (("racoon", rac), ("racoon-worker", wrk), ("racoon-gpu", gpu_m)):
        info = ready.get(key) or {}
        src["ready"] = info.get("ready", src.get("ready", True))
        if info.get("pressure"):
            src["pressure"] = True
        b = nodes.get(key) or nodes.get(key.replace("racoon-worker", "racoon-worker")) or {}
        if b and not b.get("reachable", True):
            src["ready"] = False
    gpu_node = nodes.get("racoon-gpu") or {}
    on = bool(gpu_node.get("reachable")) and bool(gpu_node.get("ssh_reachable", True))
    if not gpu_node:
        on = bool(gpu_m.get("cpu") is not None or vllm_up())
    claw_lines, claw_ok = [], None
    if on:
        claw_lines, claw_ok = openclaw_report()
    pi = pi_health()
    now_t, boot_t = throttled_flags(pi.get("throttled"))
    ram_free = pi.get("ram_free_mb")
    sd_pct = None
    if pi.get("sd_mb") and pi.get("sd_free_mb") is not None:
        sd_pct = 100 * (1 - pi["sd_free_mb"] / pi["sd_mb"])
    cam = pi.get("camera") or {}
    last = (dash.get("last_backup") or {})
    age_d = None
    if last.get("finished_at"):
        try:
            fin = datetime.fromisoformat(last["finished_at"])
            if fin.tzinfo is None:
                fin = fin.replace(tzinfo=timezone.utc)
            age_d = (datetime.now(timezone.utc) - fin).total_seconds() / 86400
        except ValueError:
            age_d = None
    storage = dash.get("storage") or {}
    ping, router = ping_ms("192.168.0.1")
    dns_ms, dns_ok = ping_ms("192.168.0.91")
    return {
        "nodes": {
            "racoon": rac,
            "worker": wrk,
        },
        "gpu": {
            "on": on,
            "should_on": should_gpu_on(),
            "vllm": vllm_up() if on else False,
            "vllm_late": False,
            "temp": gpu_m.get("temp") if on else None,
            "claw_ok": claw_ok,
            "claw_lines": claw_lines,
            "off_since": None if on else "schedule",
        },
        "pi": {
            "temp": pi.get("temp_c"),
            "ram_free": ram_free,
            "sd_pct": sd_pct,
            "throttled_now": now_t,
            "throttled_boot": boot_t,
        },
        "eater": eater(),
        "backup": {
            "last_ok": (last.get("status") == "success") if last else True,
            "overdue": age_d is not None and age_d > 8,
            "partial": last.get("status") not in (None, "success", "running"),
            "capacity_bad": storage.get("capacity_ok") is False,
            "smart_bad": False,
            "running": bool(state.get("backup_running")),
            "age_d": age_d,
            "next": _short(dash.get("tiers")),
            "archive": "ok" if storage.get("capacity_ok", True) else "low",
        },
        "net": {
            "router": router,
            "dns": dns_ok,
            "loss": 0 if router else 100,
            "ping_ms": ping,
            "dns_ms": dns_ms,
            "rssi": pi.get("wifi_rssi"),
        },
        "camera": {
            "recording": bool(cam.get("recording")),
            "elapsed_s": cam.get("elapsed_s") or 0,
            "file": cam.get("file"),
            "sd": (str(pi.get("sd_free_mb")) + "M") if pi.get("sd_free_mb") is not None else None,
        },
    }


def _short(tiers):
    if not tiers:
        return ""
    for t in tiers:
        if t.get("name") == "staging" and t.get("next_run"):
            return "next " + t["next_run"][5:16].replace("T", " ")
    return ""


def openclaw_report():
    """SSH once per refresh when the GPU node is up. Missing key is a warning, not a crit."""
    from checks import claw_lines
    key = os.environ.get("GPU_SSH_KEY", "/secrets/gpu_ssh/id_ed25519")
    if not os.path.exists(key):
        return ["openclaw: no ssh key"], False
    import subprocess
    try:
        r = subprocess.run(
            ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "dante@192.168.1.5",
             "openclaw health --json; echo '---SPLIT---'; openclaw status --json"],
            capture_output=True, text=True, timeout=12,
        )
    except Exception:
        return ["openclaw: ssh failed"], False
    if r.returncode != 0:
        return ["openclaw: ssh failed"], False
    import json
    parts = (r.stdout or "").split("---SPLIT---")
    health = status = None
    try:
        health = json.loads(parts[0])
    except Exception:
        health = None
    if len(parts) > 1:
        try:
            status = json.loads(parts[1])
        except Exception:
            status = None
    return claw_lines(health, status)


def fire(action):
    path = {"wake": "/api/actions/wol", "backup": "/api/actions/sync"}.get(action)
    if not path:
        return False
    try:
        httpx.post(BACKEPR + path, timeout=2)
        return True
    except Exception:
        return True
