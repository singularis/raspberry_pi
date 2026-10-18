"""View-model the Pi draws. States are decided here, never on the Pi."""

from datetime import datetime, timezone


def _round_text(v, suffix):
    return str(int(round(float(v)))) + suffix


def snap(tiles, next_in_s=60, temp_out=None, weather=None, sensor=None):
    warn = sum(1 for t in tiles if t["state"] == "warn")
    crit = sum(1 for t in tiles if t["state"] == "crit")
    worst = ""
    for t in tiles:
        if t["state"] == "crit":
            worst = t["id"]
            break
    if not worst:
        for t in tiles:
            if t["state"] == "warn":
                worst = t["id"]
                break
    body = {
        "schema": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "next_in_s": next_in_s,
        "summary": {"warn": warn, "crit": crit, "worst": worst},
        "tiles": tiles,
    }
    w = weather or {}
    temp = w.get("temp", temp_out)
    if temp is not None:
        body["temp_out"] = str(int(round(float(temp)))) + "\u00b0C"
    if w.get("hum") is not None:
        body["humidity"] = str(int(round(float(w["hum"])))) + "%"
    if w.get("press") is not None:
        body["pressure"] = str(int(round(float(w["press"]))))
    room = {}
    s = sensor or {}
    if s.get("temp") is not None:
        room["temp"] = _round_text(s["temp"], "\u00b0C")
        body["temp_in"] = room["temp"]
    if s.get("hum") is not None:
        room["humidity"] = _round_text(s["hum"], "%")
    if s.get("press") is not None:
        room["pressure"] = _round_text(s["press"], "")
    if room:
        body["sensor"] = room
    return body


def tile(tid, label, state, big, l2="", l3="", cap="", spark=None, pages=None, screen="", camera=None):
    return {
        "id": tid,
        "label": label,
        "state": state,
        "age_s": 0,
        "big": big,
        "cap": cap,
        "l2": l2,
        "l3": l3,
        "spark": spark or [],
        "pages": pages or [],
        "screen": screen,
        "camera": camera,
    }


def worst(*states):
    if "crit" in states:
        return "crit"
    if "warn" in states:
        return "warn"
    if "busy" in states:
        return "busy"
    if all(s == "off" for s in states):
        return "off"
    if "idle" in states and "ok" not in states:
        return "idle"
    return "ok"
