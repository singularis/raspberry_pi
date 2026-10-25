"""View-model the Pi draws. States are decided here, never on the Pi."""

from datetime import datetime, timezone


def _round_text(v, suffix):
    return str(int(round(float(v)))) + suffix


def _gas_text(ohms):
    n = float(ohms)
    if n >= 1_000_000:
        text = f"{n / 1_000_000:.1f} M"
    elif n >= 1000:
        text = str(int(round(n / 1000))) + " k"
    else:
        text = str(int(round(n))) + " "
    return text + "\u03a9"


def temp_level(c, lo_c, lo_w, hi_w, hi_c):
    if c <= lo_c or c >= hi_c:
        return "crit"
    if c <= lo_w or c >= hi_w:
        return "warn"
    return "ok"


def hum_level(v):
    if v is None:
        return ""
    v = float(v)
    if v < 15 or v > 80:
        return "crit"
    if v < 30 or v > 65:
        return "warn"
    return "ok"


def press_level(v):
    if v is None:
        return ""
    v = float(v)
    if v < 980 or v > 1045:
        return "crit"
    if v < 1000 or v > 1030:
        return "warn"
    return "ok"


def gas_level(ohms):
    if ohms is None:
        return ""
    n = float(ohms)
    if n < 20000:
        return "crit"
    if n < 50000:
        return "warn"
    return "ok"


def weather_alert(code):
    """WMO weather code. Severe is thunderstorm, heavy rain, or heavy snow."""
    if code is None:
        return ""
    c = int(code)
    if c in (65, 67, 75, 82, 86, 95, 96, 99):
        return "severe"
    if c in (45, 48, 55, 57, 63, 66, 71, 73, 81, 85):
        return "warn"
    return ""


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
        body["weather_level"] = temp_level(float(temp), -2, 3, 27, 32)
    body["weather_alert"] = weather_alert(w.get("code"))
    if w.get("hum") is not None:
        body["humidity"] = str(int(round(float(w["hum"])))) + "%"
        body["weather_hum_level"] = hum_level(w["hum"])
    if w.get("press") is not None:
        body["pressure"] = str(int(round(float(w["press"]))))
        body["weather_press_level"] = press_level(w["press"])
    room = {}
    s = sensor or {}
    if s.get("temp") is not None:
        room["temp"] = _round_text(s["temp"], "\u00b0C")
        room["level"] = temp_level(float(s["temp"]), 10, 16, 28, 32)
        body["temp_in"] = room["temp"]
    if s.get("hum") is not None:
        room["humidity"] = _round_text(s["hum"], "%")
        room["hum_level"] = hum_level(s["hum"])
    if s.get("press") is not None:
        room["pressure"] = _round_text(s["press"], "")
        room["press_level"] = press_level(s["press"])
    if s.get("gas") is not None:
        room["gas"] = _gas_text(s["gas"])
        room["gas_level"] = gas_level(s["gas"])
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
