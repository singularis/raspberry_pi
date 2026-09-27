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
EATER_DEV_HOP = os.environ.get("EATER_DEV_HOP", "http://chater-ui-dev.chater-ui-dev.svc.cluster.local:5000/dev/eater_get_today")
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
    # avg/max without "by (kubernetes_node)" drop the label and the sample is missed.
    cpu = _series(node, f'100 - (avg by (kubernetes_node) (rate(node_cpu_seconds_total{{mode="idle",kubernetes_node="{node}"}}[5m])) * 100)')
    avail = _series(node, f'node_memory_MemAvailable_bytes{{kubernetes_node="{node}"}}')
    total = _series(node, f'node_memory_MemTotal_bytes{{kubernetes_node="{node}"}}')
    disk_avail = _series(node, f'node_filesystem_avail_bytes{{kubernetes_node="{node}",mountpoint="/",fstype!="tmpfs"}}')
    disk_size = _series(node, f'node_filesystem_size_bytes{{kubernetes_node="{node}",mountpoint="/",fstype!="tmpfs"}}')
    temp = _series(node, f'max by (kubernetes_node) (node_hwmon_temp_celsius{{kubernetes_node="{node}",chip=~"platform_coretemp.*",sensor="temp1"}})')
    ram_pct = (100 * (1 - avail / total)) if avail and total else None
    disk_pct = (100 * (1 - disk_avail / disk_size)) if disk_avail and disk_size else None
    free_gb = (avail / (1024 ** 3)) if avail else None
    return {"cpu": cpu, "ram_pct": ram_pct, "disk_pct": disk_pct, "temp": temp, "free_gb": free_gb, "ready": True, "disks": node_disks(node)}


def node_disks(node):
    """Real mounts only. Skip container and snap namespaces."""
    sizes = prom(
        f'node_filesystem_size_bytes{{kubernetes_node="{node}",fstype=~"btrfs|ext4|xfs|vfat"}}'
    )
    frees = prom(
        f'node_filesystem_avail_bytes{{kubernetes_node="{node}",fstype=~"btrfs|ext4|xfs|vfat"}}'
    )
    free_by = {}
    for row in frees:
        mp = (row.get("metric") or {}).get("mountpoint")
        try:
            free_by[mp] = float(row["value"][1])
        except (KeyError, TypeError, ValueError):
            pass
    out = []
    for row in sizes:
        metric = row.get("metric") or {}
        mp = metric.get("mountpoint") or ""
        if not mp or mp.startswith("/run") or "snapd" in mp or mp.startswith("/var/lib/kubelet"):
            continue
        try:
            size = float(row["value"][1])
        except (KeyError, TypeError, ValueError):
            continue
        if size < 500 * 1024 * 1024 and mp != "/boot/efi":
            continue
        free = free_by.get(mp)
        pct = (100 * (1 - free / size)) if free is not None and size else None
        name = "root" if mp == "/" else mp.strip("/").replace("/", "-")
        out.append({"name": name, "pct": pct, "free_gb": (free / (1024 ** 3)) if free else None})
    out.sort(key=lambda d: -(d["free_gb"] or 0))
    return out


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
        return base64.b64decode(raw).decode().strip() if raw else None
    except Exception:
        return None


def mint(secret):
    now = int(time.time())
    return jwt.encode(
        {"sub": SYNTH_EMAIL, "iat": now, "exp": now + 300, "name": "lcd-synthetic", "picture": ""},
        secret,
        algorithm="HS256",
    )


def _varint(buf, i):
    n = s = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << s
        if not b & 0x80:
            return n, i
        s += 7
    return n, i


def dish_count(buf):
    """Count TodayFood.dishes_today (field 1) from chater's protobuf reply."""
    i = n = 0
    while i < len(buf):
        key, j = _varint(buf, i)
        if j == i:
            break
        i = j
        field, wt = key >> 3, key & 7
        if wt == 0:
            _, i = _varint(buf, i)
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        elif wt == 2:
            ln, i = _varint(buf, i)
            if field == 1:
                n += 1
            i += ln
        else:
            break
    return n


def _get_eater(url, token):
    t0 = time.monotonic()
    try:
        r = httpx.get(url, headers={"Authorization": "Bearer " + token, "User-Agent": UA}, timeout=15)
    except Exception as exc:
        return False, None, None, type(exc).__name__
    ms = int((time.monotonic() - t0) * 1000)
    dishes = None
    if r.status_code == 200:
        ctype = (r.headers.get("content-type") or "").lower()
        if "protobuf" in ctype or (r.content and r.content[:1] == b"\n"):
            dishes = dish_count(r.content)
        else:
            try:
                body = r.json()
            except Exception:
                body = None
            if isinstance(body, list):
                dishes = len(body)
            elif isinstance(body, dict):
                dishes = body.get("count") or len(body.get("dishes") or body.get("items") or [])
    return r.status_code == 200, ms, dishes, str(r.status_code)


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
        ok, ms, dishes, code = _get_eater(EATER_PROD, mint(prod_secret))
        out.update(prod_ok=ok, prod_ms=ms, dishes=dishes, hop="public " + code)
        if not ok:
            ok2, ms2, dishes2, code2 = _get_eater(EATER_PROD_HOP, mint(prod_secret))
            out.update(prod_ok=ok2, prod_ms=ms2, dishes=dishes2, hop="chater-ui:5000 " + code2)
    if dev_secret:
        ok, _, _, code = _get_eater(EATER_DEV, mint(dev_secret))
        out["dev_ok"] = ok
        if not ok:
            ok2, _, _, code2 = _get_eater(EATER_DEV_HOP, mint(dev_secret))
            out["dev_ok"] = ok2
            out["hop"] = (out["hop"] + " dev:" + code2).strip()
    out["argo_bad"] = argo_bad()
    users, scans, anon, anon_scans = eater_today()
    out["users_today"] = users
    out["scans_today"] = scans
    out["anon_today"] = anon
    out["anon_scans"] = anon_scans
    try:
        stats = httpx.get("http://192.168.0.113/api/stats", timeout=4).json().get("statistics") or {}
        out["active_7d"] = stats.get("active_users_7_days")
    except Exception:
        out["active_7d"] = None
    return out


def eater_today():
    """New registered users and dish scans for today. Read-only on the eater DB."""
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return None, None, None, None
    try:
        import base64
        import psycopg2
        token = open(token_path).read()
        r = httpx.get(
            "https://kubernetes.default.svc/api/v1/namespaces/eater/secrets/eater.eater-db.credentials.postgresql.acid.zalan.do",
            headers={"Authorization": "Bearer " + token},
            verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            timeout=4,
        )
        r.raise_for_status()
        data = r.json()["data"]
        user = base64.b64decode(data["username"]).decode()
        password = base64.b64decode(data["password"]).decode()
        conn = psycopg2.connect(host="eater-db.eater.svc.cluster.local", dbname="eater", user=user, password=password, connect_timeout=4)
        try:
            cur = conn.cursor()
            cur.execute("""SELECT COUNT(*) FROM public."user" WHERE register_date::date = CURRENT_DATE AND email <> 'test@test.com' AND email NOT LIKE 'anon_%@anonymous.local'""")
            users = cur.fetchone()[0]
            cur.execute("""SELECT COUNT(*) FROM public."user" WHERE register_date::date = CURRENT_DATE AND email LIKE 'anon_%@anonymous.local'""")
            anon = cur.fetchone()[0]
            cur.execute("""SELECT COUNT(*) FROM dishes_day WHERE date = CURRENT_DATE AND user_email <> 'test@test.com'""")
            scans = cur.fetchone()[0]
            cur.execute("""SELECT COUNT(*) FROM dishes_day WHERE date = CURRENT_DATE AND user_email LIKE 'anon_%@anonymous.local'""")
            anon_scans = cur.fetchone()[0]
            return int(users), int(scans), int(anon), int(anon_scans)
        finally:
            conn.close()
    except Exception:
        return None, None, None, None


def google_times():
    """ICMP ping to google.com and how long a DNS lookup of that name takes."""
    dns_ms = None
    t0 = time.monotonic()
    try:
        socket.getaddrinfo("google.com", 443, type=socket.SOCK_STREAM)
        dns_ms = int((time.monotonic() - t0) * 1000)
    except Exception:
        dns_ms = None
    ping = None
    try:
        import re
        import subprocess
        r = subprocess.run(["ping", "-c", "1", "-W", "2", "google.com"], capture_output=True, text=True, timeout=4)
        m = re.search(r"time[=<]([0-9.]+)", r.stdout or "")
        if m:
            ping = float(m.group(1))
    except Exception:
        ping = None
    return ping, dns_ms


def tcp_ms(host, port, timeout=1):
    """Same reachability test Backepr uses: a short TCP connect, not ICMP."""
    t0 = time.monotonic()
    try:
        socket.create_connection((host, port), timeout).close()
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
    gpu_temp = gpu_m.get("temp") if on else None
    gpu_watts = None
    if on:
        claw_lines, claw_ok, extra = openclaw_report()
        if extra.get("temp") is not None:
            gpu_temp = extra["temp"]
        gpu_watts = extra.get("watts")
    notes = _notes()
    spark = list(notes.get("worker") or [])
    if wrk.get("free_gb") is not None:
        spark = (spark + [round(wrk["free_gb"], 2)])[-16:]
        notes["worker"] = spark
    wrk["spark"] = spark
    should = should_gpu_on()
    vllm = vllm_up() if on else False
    since = notes.get("vllm_down_since")
    now_ts = time.time()
    if on and should and not vllm:
        if not since:
            since = now_ts
        notes["vllm_down_since"] = since
        vllm_late = now_ts - float(since) > 900
    else:
        notes["vllm_down_since"] = None
        vllm_late = False
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
    ping, router = tcp_ms("192.168.0.1", 80)
    _, dns_ok = tcp_ms("192.168.0.91", 53)
    google_ms, dns_ms = google_times()
    _, internet = tcp_ms("1.1.1.1", 443)
    staging = storage_body("staging")
    archive = storage_body("archive")
    hole = pihole()
    down_b = nic_rate("receive")
    up_b = nic_rate("transmit")
    pi["cpu"] = pi_cpu(pi.get("cpu_total"), pi.get("cpu_idle"), notes)
    _save_notes(notes)
    return {
        "nodes": {
            "racoon": rac,
            "worker": wrk,
        },
        "gpu": {
            "on": on,
            "should_on": should_gpu_on(),
            "vllm": vllm,
            "vllm_late": vllm_late,
            "temp": gpu_temp,
            "cpu": gpu_m.get("cpu"),
            "ram_pct": gpu_m.get("ram_pct"),
            "free_gb": gpu_m.get("free_gb"),
            "cpu_temp": gpu_m.get("temp"),
            "watts": gpu_watts,
            "extra_disks": _extra_disks(rac),
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
            "wifi": pi.get("wifi_rssi"),
            "cpu": pi.get("cpu"),
            "ram_mb": pi.get("ram_mb"),
            "sd_free_mb": pi.get("sd_free_mb"),
        },
        "eater": eater(),
        "backup": {
            "last_ok": (last.get("status") == "success") if last else True,
            "overdue": age_d is not None and age_d > 8,
            "partial": last.get("status") not in (None, "success", "running"),
            "capacity_bad": storage.get("capacity_ok") is False,
            "smart_bad": smart_bad(),
            "running": bool(state.get("backup_running")),
            "age_d": age_d,
            "next": _short(dash.get("tiers")),
            "archive": "ok" if storage.get("capacity_ok", True) else "low",
            "staging_free_gb": _gib(staging.get("free_bytes")),
            "staging_used_pct": staging.get("percent_used"),
            "archive_free_gb": _gib(archive.get("free_bytes")),
            "archive_used_pct": archive.get("percent_used"),
            "archive_mounted": bool(archive.get("mounted")),
        },
        "net": {
            "router": router,
            "dns": dns_ok,
            "loss": 0 if router else 100,
            "ping_ms": ping,
            "google_ms": google_ms,
            "dns_ms": dns_ms,
            "rssi": pi.get("wifi_rssi"),
            "pihole": hole.get("up"),
            "pihole_blocked": hole.get("blocked"),
            "down": _rate(down_b),
            "up": _rate(up_b),
            "internet": internet,
        },
        "camera": {
            "recording": bool(cam.get("recording")),
            "elapsed_s": cam.get("elapsed_s") or 0,
            "file": cam.get("file"),
            "sd": (str(pi.get("sd_free_mb")) + "M") if pi.get("sd_free_mb") is not None else None,
        },
    }


def _extra_disks(rac):
    staging = storage_body("staging")
    archive = storage_body("archive")
    disks = [
        {"name": "staging", "pct": staging.get("percent_used") if staging.get("mounted") else None, "free_gb": _gib(staging.get("free_bytes")) if staging.get("mounted") else None},
        {"name": "archive", "pct": archive.get("percent_used") if archive.get("mounted") else None, "free_gb": _gib(archive.get("free_bytes")) if archive.get("mounted") else None},
        {"name": "proxmox", "pct": None, "free_gb": None},
    ]
    for d in rac.get("disks") or []:
        if d.get("name") == "root":
            disks.append({"name": "racoon", "pct": d.get("pct"), "free_gb": d.get("free_gb")})
    return disks


def storage_body(kind):
    try:
        return httpx.get(BACKEPR + "/api/dashboard/storage/" + kind, timeout=8).json()
    except Exception:
        return {}


def pihole():
    try:
        r = httpx.get("http://192.168.0.92/api/stats/summary", timeout=3)
        if r.status_code != 200:
            return {"up": False, "blocked": None}
        q = (r.json().get("queries") or {})
        return {"up": True, "blocked": q.get("percent_blocked")}
    except Exception:
        return {"up": False, "blocked": None}


def nic_rate(direction):
    rows = prom(f'rate(node_network_{direction}_bytes_total{{kubernetes_node="racoon",device="eth0"}}[2m])')
    if not rows:
        return None
    try:
        return float(rows[0]["value"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def pi_cpu(total, idle, notes):
    if total is None or idle is None:
        return None
    prev = notes.get("pi_cpu")
    notes["pi_cpu"] = [total, idle]
    if not prev or len(prev) != 2:
        return None
    dt = total - prev[0]
    di = idle - prev[1]
    if dt <= 0:
        return None
    return 100 * (1 - di / dt)


def _gib(n):
    if not n:
        return None
    return n / (1024 ** 3)


def _rate(b):
    if b is None:
        return "--"
    if b >= 1_000_000:
        return f"{b/1_000_000:.1f}M"
    if b >= 1000:
        return f"{b/1000:.0f}k"
    return f"{b:.0f}"


def _short(tiers):
    if not tiers:
        return ""
    for t in tiers:
        if t.get("name") == "staging" and t.get("next_run"):
            return "next " + t["next_run"][5:16].replace("T", " ")
    return ""


def argo_bad():
    """Warn when a Chater or Eater Argo app is degraded. Same objects Argo already tracks."""
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return False
    try:
        token = open(token_path).read()
        r = httpx.get(
            "https://kubernetes.default.svc/apis/argoproj.io/v1alpha1/namespaces/argocd/applications",
            headers={"Authorization": "Bearer " + token},
            verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            timeout=4,
        )
        r.raise_for_status()
        for item in r.json().get("items", []):
            name = item.get("metadata", {}).get("name", "")
            if "eater" not in name and "chater" not in name:
                continue
            health = ((item.get("status") or {}).get("health") or {}).get("status")
            if health not in (None, "Healthy"):
                return True
        return False
    except Exception:
        return False


def smart_bad():
    try:
        rows = httpx.get(BACKEPR + "/api/health/smart", timeout=8).json()
    except Exception:
        return False
    if not isinstance(rows, list):
        return False
    return any(isinstance(row, dict) and row.get("healthy") is False for row in rows)


def _notes():
    try:
        from lease import load_notes
        return load_notes()
    except Exception:
        return {}


def _save_notes(data):
    try:
        from lease import save_notes
        save_notes(data)
    except Exception:
        pass


def _gpu_key():
    path = os.environ.get("GPU_SSH_KEY", "/tmp/gpu_ssh_key")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return None
    try:
        import base64
        token = open(token_path).read()
        r = httpx.get(
            "https://kubernetes.default.svc/api/v1/namespaces/backepr/secrets/backepr-secrets",
            headers={"Authorization": "Bearer " + token},
            verify="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            timeout=4,
        )
        r.raise_for_status()
        raw = r.json()["data"].get("SSH_PRIVATE_KEY")
        if not raw:
            return None
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(raw))
        os.chmod(path, 0o600)
        return path
    except Exception:
        return None


def openclaw_report():
    """SSH with Backepr's key. OpenClaw is a warning. nvidia-smi supplies GPU temp and watts."""
    from checks import claw_lines
    key = _gpu_key()
    if not key:
        return ["openclaw: no ssh key"], False, {}
    import subprocess
    try:
        r = subprocess.run(
            ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/tmp/known_hosts", "-o", "ConnectTimeout=5",
             "dante@192.168.1.5",
             "openclaw health --json; echo '---SPLIT---'; openclaw status --json; echo '---SPLIT---'; nvidia-smi --query-gpu=temperature.gpu,power.draw --format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return ["openclaw: ssh failed"], False, {}
    if r.returncode != 0:
        return ["openclaw: ssh failed"], False, {}
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
    extra = {}
    if len(parts) > 2:
        bits = parts[2].strip().split(",")
        if bits and bits[0].strip().replace(".", "", 1).isdigit():
            extra["temp"] = float(bits[0])
        if len(bits) > 1:
            try:
                extra["watts"] = float(bits[1].strip().split()[0])
            except ValueError:
                pass
    lines, ok = claw_lines(health, status)
    return lines, ok, extra


def fire(action):
    path = {"wake": "/api/actions/wol", "backup": "/api/actions/sync"}.get(action)
    if not path:
        return False
    try:
        httpx.post(BACKEPR + path, timeout=2)
        return True
    except Exception:
        return True
