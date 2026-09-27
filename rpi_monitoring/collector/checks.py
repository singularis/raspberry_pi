"""Classify fetched facts. No network in this module."""

from model import tile, worst


def node_state(ready, cpu, ram_pct, disk_pct, temp, free_gb=None, pressure=False, majfault=False):
    if ready is False:
        return "crit"
    if all(v is None for v in (cpu, ram_pct, disk_pct, temp, free_gb)):
        return "stale"
    states = []
    if disk_pct is not None and disk_pct > 95:
        states.append("crit")
    elif disk_pct is not None and disk_pct > 85:
        states.append("warn")
    if free_gb is not None and free_gb < 0.7:
        states.append("crit")
    elif free_gb is not None and free_gb < 1.0:
        states.append("warn")
    if ram_pct is not None and ram_pct > 90 and free_gb is None:
        states.append("warn")
    if cpu is not None and cpu > 85:
        states.append("warn")
    if temp is not None and temp > 85:
        states.append("warn")
    if pressure or majfault:
        states.append("warn")
    return worst("ok", *states)


def gpu_state(on, should_on, vllm_ready, vllm_late, claw_ok, temp):
    if not on:
        return "off"
    states = ["ok"]
    if should_on and not vllm_ready and vllm_late:
        states.append("crit")
    if temp is not None and temp > 83:
        states.append("warn")
    if claw_ok is False:
        states.append("warn")
    return worst(*states)


def pi_state(temp, ram_free, sd_pct, throttled_now, throttled_boot):
    if temp is None and ram_free is None and sd_pct is None and not throttled_now and not throttled_boot:
        return "stale"
    states = ["ok"]
    if throttled_now or (ram_free is not None and ram_free < 30) or (sd_pct is not None and sd_pct > 95):
        states.append("crit")
    if throttled_boot or (temp is not None and temp > 70) or (ram_free is not None and ram_free < 60) or (sd_pct is not None and 85 < (sd_pct or 0) <= 95):
        states.append("warn")
    return worst(*states)


def eater_state(prod_ok, prod_ms, dev_ok, health_ok, argo_bad, stats_bad):
    if not prod_ok or not health_ok:
        return "crit"
    states = ["ok"]
    if not dev_ok or (prod_ms is not None and prod_ms > 1000) or argo_bad or stats_bad:
        states.append("warn")
    return worst(*states)


def backup_state(last_ok, overdue, partial, capacity_bad, smart_bad, running):
    if running:
        return "busy"
    if not last_ok or smart_bad:
        return "crit"
    if overdue or partial or capacity_bad:
        return "warn"
    return "ok"


def net_state(router_up, dns_up, loss, ping_ms, dns_ms, rssi, internet=True):
    if not router_up or not dns_up or not internet:
        return "crit"
    states = ["ok"]
    if (loss is not None and loss > 2) or (ping_ms is not None and ping_ms > 80) or (dns_ms is not None and dns_ms > 200) or (rssi is not None and rssi < -75):
        states.append("warn")
    return worst(*states)


def claw_lines(health, status):
    """Map openclaw health --json and status --json. Never a crit by itself."""
    lines = []
    if not health:
        return ["openclaw: no report"], False
    ok = bool(health.get("ok"))
    plugins = (health.get("plugins") or {}).get("errors") or []
    tg = ((health.get("channels") or {}).get("telegram") or {})
    lines.append("gateway " + ("ok" if ok else "not ok"))
    if plugins:
        lines.append("plugin errors " + str(len(plugins)))
    if tg:
        lines.append("telegram " + ("up" if tg.get("connected") else "down"))
    tasks = (status or {}).get("tasks") or {}
    if tasks:
        lines.append("tasks fail " + str(tasks.get("failures") or 0))
    audit = (status or {}).get("taskAudit") or {}
    if audit.get("errors"):
        lines.append("audit errors " + str(audit.get("errors")))
    good = ok and not plugins and (not tg or tg.get("connected")) and not (tasks.get("failures") or 0) and not audit.get("errors")
    return lines[:4], good


def build(facts):
    n = facts.get("nodes") or {}
    rac = n.get("racoon") or {}
    wrk = n.get("worker") or {}
    gpu = facts.get("gpu") or {}
    pi = facts.get("pi") or {}
    eat = facts.get("eater") or {}
    bak = facts.get("backup") or {}
    net = facts.get("net") or {}
    cam = facts.get("camera") or {}

    tiles = [
        tile(
            "racoon", "RACOON",
            node_state(rac.get("ready", True), rac.get("cpu"), rac.get("ram_pct"), rac.get("disk_pct"), rac.get("temp")),
            big=_pct(rac.get("cpu"), "cpu"),
            l2="ram " + _pct(rac.get("ram_pct"), ""),
            l3=_temp(rac.get("temp")),
            pages=_node_rows(rac, ["root", "other_ssd", "other_hdd"]),
        ),
        tile(
            "worker", "WORKER",
            node_state(wrk.get("ready", True), wrk.get("cpu"), None, wrk.get("disk_pct"), wrk.get("temp"), wrk.get("free_gb"), wrk.get("pressure"), wrk.get("majfault")),
            big=_gb(wrk.get("free_gb")),
            cap="ram free",
            l2="cpu " + _pct(wrk.get("cpu"), ""),
            l3=_temp(wrk.get("temp")),
            spark=wrk.get("spark") or [],
            pages=_node_rows(wrk, ["root"]),
        ),
        _gpu_tile(gpu),
        _pi_tile(pi),
        _eater_tile(eat),
        _backup_tile(bak),
        tile(
            "network", "NETWORK",
            net_state(net.get("router", True), net.get("dns", True), net.get("loss"), net.get("ping_ms"), net.get("dns_ms"), net.get("rssi"), net.get("internet", True)),
            big=_ms(net.get("google_ms")),
            l2="dns " + _ms(net.get("dns_ms")),
            l3=("pihole " + ("up" if net.get("pihole") else "down")),
            pages=[{"rows": [
                _row("google", _ms(net.get("google_ms")), _lvl_high(net.get("google_ms"), 80, 200)),
                _row("dns", _ms(net.get("dns_ms")), _lvl_high(net.get("dns_ms"), 80, 200)),
                _row("pihole", ("up " + _pct(net.get("pihole_blocked"), "")) if net.get("pihole") else "down", "ok" if net.get("pihole") else "crit"),
                _row("down", net.get("down") or "--", "ok"),
                _row("up", net.get("up") or "--", "ok"),
            ]}],
        ),
        _camera_tile(cam),
    ]
    return tiles


def _gpu_tile(gpu):
    on = bool(gpu.get("on"))
    should = bool(gpu.get("should_on"))
    claw_ok = gpu.get("claw_ok")
    st = gpu_state(on, should, gpu.get("vllm"), gpu.get("vllm_late"), claw_ok, gpu.get("temp"))
    watts = gpu.get("watts")
    watt_s = "" if watts is None else " " + str(int(round(watts))) + "W"
    if not on:
        big, l2 = "OFF", "since " + (gpu.get("off_since") or "--")
    else:
        big, l2 = _temp(gpu.get("temp")), "vllm " + ("up" if gpu.get("vllm") else "down") + watt_s
    node = {
        "cpu": gpu.get("cpu"),
        "ram_pct": gpu.get("ram_pct"),
        "free_gb": gpu.get("free_gb"),
        "temp": gpu.get("cpu_temp"),
        "gpu_temp": gpu.get("temp"),
        "disks": list(gpu.get("disks") or []),
    }
    for extra in gpu.get("extra_disks") or []:
        node["disks"].append(extra)
    pages = _node_rows(node, ["staging", "archive", "proxmox", "racoon", "root"])
    if gpu.get("claw_lines"):
        pages.append({"rows": [_row("claw", ln, "warn" if claw_ok is False else "ok") for ln in gpu.get("claw_lines")[:4]]})
    if not on:
        pages.append({"actions": [{
            "id": "wake",
            "label": "Wake GPU",
            "enabled": True,
            "why": "",
            "confirm": {"title": "Wake GPU host?", "body": "Boots Proxmox and racoon-gpu"},
        }]})
    return tile("gpu", "GPU", st, big, l2=l2, l3="openclaw " + ("ok" if claw_ok else "warn" if claw_ok is False else "--"), pages=pages)


def _pi_tile(pi):
    sd = pi.get("sd_pct")
    st = pi_state(pi.get("temp"), pi.get("ram_free"), sd, pi.get("throttled_now"), pi.get("throttled_boot"))
    power = "bad" if pi.get("throttled_now") or pi.get("throttled_boot") else "ok"
    free_mb = pi.get("ram_free")
    total_mb = pi.get("ram_mb")
    free_pct = (100 * free_mb / total_mb) if free_mb and total_mb else None
    pi_node = {"cpu": pi.get("cpu"), "free_gb": (free_mb / 1024) if free_mb is not None else None, "ram_pct": (100 - free_pct) if free_pct is not None else None, "temp": pi.get("temp")}
    rows = [_cpu_row(pi.get("cpu")), _ram_row(pi_node)]
    rows.append(_disk_row("sd", pi.get("sd_pct"), (pi.get("sd_free_mb") or 0) / 1024 if pi.get("sd_free_mb") is not None else None))
    rows.append(_temp_row("temp", pi.get("temp"), 70, 80))
    rows.append(_row("power", power, "crit" if power == "bad" else "ok"))
    return tile(
        "pi", "PI", st,
        _temp(pi.get("temp")),
        cap="cpu temp",
        l2="ram " + (str(pi.get("ram_free")) + "M" if pi.get("ram_free") is not None else "--"),
        l3="power " + power,
        pages=[{"rows": rows}],
    )


def _eater_tile(eat):
    st = eater_state(eat.get("prod_ok", True), eat.get("prod_ms"), eat.get("dev_ok", True), eat.get("health_ok", True), eat.get("argo_bad"), eat.get("stats_bad"))
    dishes = eat.get("dishes")
    big = ("+" + str(dishes)) if dishes is not None else "--"
    hop = eat.get("hop") or ""
    l3 = "prod+dev ok" if st == "ok" else (hop or "check failed")
    return tile(
        "eateria", "EATERIA", st, big,
        l2="dishes today",
        l3=l3,
        pages=[{"rows": [
            _row("scans", _n(eat.get("scans_today")), "ok"),
            _row("users", _n(eat.get("users_today")), "ok"),
            _row("anon", _n(eat.get("anon_today")), "ok"),
            _row("ascans", _n(eat.get("anon_scans")), "ok"),
            _row("dishes", _n(eat.get("dishes")), "ok"),
            _row("7d", _n(eat.get("active_7d")), "ok"),
        ]}],
    )


def _backup_tile(bak):
    st = backup_state(bak.get("last_ok", True), bak.get("overdue"), bak.get("partial"), bak.get("capacity_bad"), bak.get("smart_bad"), bak.get("running"))
    stag = bak.get("staging_free_gb")
    arch = bak.get("archive_free_gb")
    arch_on = bak.get("archive_mounted")
    big = "RUN" if bak.get("running") else (_tb(stag) if stag is not None else _ago(bak.get("age_d")))
    pages = [{"actions": [{
        "id": "backup",
        "label": "Run backup",
        "enabled": not bak.get("running"),
        "why": "already running" if bak.get("running") else "",
        "confirm": {"title": "Run backup now?", "body": "Starts the staging sync"},
    }]}]
    cap = "arc off" if arch_on is False else ("arc " + _tb(arch))
    if bak.get("running"):
        cap = "running"
    pages = [{"rows": [
        _disk_row("staging", bak.get("staging_used_pct"), stag),
        _disk_row("archive", bak.get("archive_used_pct"), arch) if arch_on else _row("archive", "off", "off"),
        _row("last", _ago(bak.get("age_d")), "ok" if bak.get("last_ok", True) else "crit"),
    ], "actions": pages[0]["actions"]}]
    return tile("backup", "BACKUP", st, big, cap=cap, l2=bak.get("next") or "", l3="archive " + (bak.get("archive") or "--"), pages=pages)


def _camera_tile(cam):
    rec = bool(cam.get("recording"))
    return tile(
        "camera", "CAMERA",
        "crit" if rec else "idle",
        "REC" if rec else "ready",
        cap=("elapsed " + str(cam.get("elapsed_s") or 0) + "s") if rec else "SD " + (cam.get("sd") or "--"),
        l2=cam.get("file") or "",
        l3="",
        screen="camera",
        camera={"recording": rec, "elapsed_s": cam.get("elapsed_s") or 0, "max_s": 1800, "phase": "recording" if rec else "idle"},
    )


def _lvl_high(v, warn, crit):
    if v is None:
        return "stale"
    if v >= crit:
        return "crit"
    if v >= warn:
        return "warn"
    return "ok"


def _lvl_low(v, warn, crit):
    if v is None:
        return "stale"
    if v <= crit:
        return "crit"
    if v <= warn:
        return "warn"
    return "ok"


def _row(label, value, state="ok"):
    return [label, value, state]


def _cpu_row(pct):
    return _row("cpu", _pct(pct, ""), _lvl_high(pct, 75, 90))


def _ram_row(node):
    used = node.get("ram_pct")
    free_pct = (100 - used) if used is not None else None
    free_gb = node.get("free_gb")
    mb = int(round(free_gb * 1024)) if free_gb is not None else None
    if free_pct is None and mb is None:
        text, st = "--", "stale"
    else:
        text = _pct(free_pct, "")
        if mb is not None:
            text = text + " " + str(mb) + "M"
        st = _lvl_low(free_gb, 1.0, 0.7) if free_gb is not None and free_gb < 2 else _lvl_low(free_pct, 20, 10)
    return _row("ram", text, st)


def _temp_row(label, celsius, warn, crit):
    return _row(label, _temp(celsius), _lvl_high(celsius, warn, crit))


def _disk_row(name, pct_used, free_gb):
    text = _gb(free_gb)
    if pct_used is not None:
        free_pct = max(0, 100 - pct_used)
        text = _pct(free_pct, "") + " " + text
    return _row(name, text, _lvl_high(pct_used, 85, 95))


def _pick_disks(disks, names):
    by = {d.get("name"): d for d in disks or []}
    return [by[n] for n in names if n in by]


def _node_rows(node, disk_names, gpu_temp=None):
    rows = [_cpu_row(node.get("cpu")), _ram_row(node)]
    for d in _pick_disks(node.get("disks"), disk_names):
        rows.append(_disk_row(d.get("name") or "disk", d.get("pct"), d.get("free_gb")))
    rows.append(_temp_row("temp", node.get("temp"), 75, 85))
    if gpu_temp is not None or node.get("gpu_temp") is not None:
        rows.append(_temp_row("gpu", node.get("gpu_temp", gpu_temp), 83, 90))
    pages = []
    for i in range(0, len(rows), 6):
        pages.append({"rows": rows[i:i + 6]})
    return pages


def _n(v):
    return "--" if v is None else str(v)


def _pct(v, suffix):
    if v is None:
        return "--"
    s = str(int(round(v))) + "%"
    return s + suffix if suffix and suffix not in s else s


def _temp(v):
    if v is None:
        return "--"
    return str(int(round(v))) + "C"


def _gb(v):
    if v is None:
        return "--"
    return f"{v:.1f}G"


def _ms(v):
    if v is None:
        return "--"
    return str(int(round(v))) + "ms"


def _tb(gb):
    if gb is None:
        return "--"
    if gb >= 1024:
        return f"{gb/1024:.1f}T"
    return f"{gb:.0f}G"


def _ago(days):
    if days is None:
        return "--"
    return str(int(days)) + "d"
