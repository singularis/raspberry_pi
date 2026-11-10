"""Switch the GPU box between Linux and Windows, or power it.

The Pi only sends an action id. This module runs the long job: Wake-on-LAN,
then one SSH to Proxmox, which does the drain under systemd so a dropped
session cannot leave the cluster half-drained.

A target that does not answer within 10 minutes is tried once more. A quorum
abort is not a timeout and is not retried.
"""

import os
import socket
import subprocess
import threading
import time

PROXMOX = os.environ.get("PROXMOX_SSH", "root@192.168.0.12")
LINUX = os.environ.get("GPU_LINUX_SSH", "dante@192.168.1.5")
WINDOWS = os.environ.get("GPU_WINDOWS_SSH", "")
MAC = os.environ.get("GPU_WOL_MAC", "18:c0:4d:e0:a4:5d")
PROXMOX_IP = os.environ.get("PROXMOX_IP", "192.168.0.12")
REPLY_S = int(os.environ.get("OS_REPLY_S", "600"))
POLL_S = 15

_mu = threading.Lock()
_job = {"running": False, "phase": "", "error": "", "target": ""}
_mem = {"os_mode": "", "os_mode_at": 0.0}


def detect(probe):
    """probe keys: job, unit, linux, proxmox, windows, ping, remembered, remembered_age."""
    if probe.get("job") or probe.get("unit"):
        return "switching"
    if probe.get("linux"):
        return "linux"
    if probe.get("proxmox"):
        return "proxmox"
    if probe.get("windows"):
        return "windows"
    if probe.get("remembered") == "windows":
        age = probe.get("remembered_age")
        if probe.get("ping") or age is None or age < REPLY_S:
            return "windows"
    return "off"


def host_down(probe):
    """Nothing answers. A running power-off job must not count as the machine still being up."""
    return not probe.get("linux") and not probe.get("proxmox") and not probe.get("windows") and not probe.get("ping")


def reached(goal, probe):
    if goal == "linux":
        return bool(probe.get("linux"))
    if goal == "off":
        return host_down(probe)
    if goal == "windows":
        if probe.get("linux") or probe.get("proxmox"):
            return False
        # Ping of the Proxmox NIC, or Windows SSH. Remembering the tap is not enough:
        # the box is silent for a minute while it reboots.
        return bool(probe.get("windows") or probe.get("ping"))
    return False


class Ops:
    """Real host calls. Tests pass a fake with the same methods."""

    def probe(self):
        linux = _ssh_ok(LINUX, "echo ok")
        proxmox = False if linux else _ssh_ok(PROXMOX, "echo ok")
        unit = False
        if proxmox or linux:
            unit = _unit_active()
        windows = bool(WINDOWS) and _ssh_ok(WINDOWS, "echo ok")
        ping = False
        if not linux and not proxmox:
            ping = _ping(PROXMOX_IP)
        mem = _remembered()
        age = None
        if mem.get("os_mode_at"):
            age = time.time() - float(mem["os_mode_at"])
        with _mu:
            job = _job["running"]
        return {
            "job": job,
            "unit": unit,
            "linux": linux,
            "proxmox": proxmox,
            "windows": windows,
            "ping": ping,
            "remembered": mem.get("os_mode") or "",
            "remembered_age": age,
        }

    def wol(self):
        _magic(MAC)

    def windows_to_linux(self):
        """Part 2 script on the Windows box. No host configured yet returns noway."""
        if not WINDOWS:
            return "noway"
        ok = _ssh_ok(WINDOWS, "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\ops\\switch_to_linux.ps1")
        return "down" if ok else "fail"

    def windows_off(self):
        if not WINDOWS:
            return "noway"
        for cmd in windows_off_commands():
            if _ssh_ok(WINDOWS, cmd):
                return "down"
        return "fail"

    def remote(self, mode):
        """Start switch_os.sh and block until it reboots, finishes, or aborts."""
        if not _ssh_ok(PROXMOX, "echo ok"):
            return "down"
        started = _ssh_ok(
            PROXMOX,
            "systemctl reset-failed os-switch 2>/dev/null; "
            "systemd-run --collect --unit=os-switch /root/proxmox/switch_os.sh " + mode,
        )
        if not started:
            text = _ssh_text(PROXMOX, "cat /run/os-switch.status 2>/dev/null || true")
            if "failed" in text:
                return "abort" if "quorum" in text else "fail"
            return "fail"
        deadline = time.time() + 25 * 60
        while time.time() < deadline:
            if not _ssh_ok(PROXMOX, "echo ok"):
                return "down"
            text = _ssh_text(PROXMOX, "cat /run/os-switch.status 2>/dev/null || true")
            active = _ssh_text(PROXMOX, "systemctl is-active os-switch 2>/dev/null || true").strip()
            if text.startswith("failed"):
                return "abort" if "quorum" in text else "fail"
            if active != "active":
                return "done"
            time.sleep(POLL_S)
        return "timeout"

    def sleep(self, seconds):
        time.sleep(seconds)

    def now(self):
        return time.time()

    def phase(self, text):
        _set(phase=text)

    def remember(self, mode):
        _remember(mode)


def windows_off_commands():
    """The ops script first. shutdown is on every Windows install if that file is missing."""
    return (
        "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\ops\\poweroff.ps1",
        "shutdown /s /t 0 /f",
    )


def nightly_due(now, os_name, done_day="", hour=22):
    """True after 22:00 London while the GPU box is still in Windows.

    Proxmox's 22:00 cron is not running then. The collector sends the power-off
    again if the last attempt failed. done_day is ignored.
    """
    if os_name != "windows":
        return False
    if now.hour < hour:
        return False
    return True


def run(goal, ops):
    """goal is linux, windows, or off. Returns ok, already, abort, noway, or no reply."""
    if _already(goal, ops.probe()):
        return "already"
    for attempt in (1, 2):
        ops.phase("starting" if attempt == 1 else "retry")
        result = _step(goal, ops)
        if result == "abort":
            ops.phase("failed")
            return "abort"
        if result == "noway":
            ops.phase("failed")
            return "noway"
        # timeout: the step already used the 10 minutes. fail: the script never started.
        # Neither should sit for another 10 minutes before the one retry.
        if result not in ("timeout", "fail") and _wait_reply(goal, ops):
            ops.phase("")
            return "ok"
        if attempt == 1:
            ops.phase("retry")
    ops.phase("failed")
    return "no reply"


def _already(goal, probe):
    if probe.get("job") or probe.get("unit"):
        return False
    if goal == "linux":
        return bool(probe.get("linux"))
    if goal == "windows":
        return detect(probe) == "windows"
    if goal == "off":
        return detect(probe) == "off"
    return False


def _step(goal, ops):
    probe = ops.probe()
    if goal == "linux":
        return _step_linux(ops, probe)
    if goal == "windows":
        return _step_windows(ops, probe)
    return _step_off(ops, probe)


def _step_linux(ops, probe):
    if probe.get("linux"):
        return "done"
    if detect(probe) == "windows" or probe.get("windows"):
        ops.phase("rebooting")
        return ops.windows_to_linux()
    if not probe.get("proxmox"):
        ops.phase("waking")
        ops.wol()
        if not _wait_until(ops, lambda p: p.get("proxmox") or p.get("linux"), REPLY_S):
            return "timeout"
        probe = ops.probe()
        if probe.get("linux"):
            return "done"
    ops.phase("starting")
    return ops.remote("linux")


def _step_windows(ops, probe):
    if _already("windows", probe):
        return "done"
    if not probe.get("proxmox") and not probe.get("linux"):
        ops.phase("waking")
        ops.wol()
        if not _wait_until(ops, lambda p: p.get("proxmox") or p.get("linux") or p.get("ping"), REPLY_S):
            return "timeout"
        probe = ops.probe()
        if _already("windows", probe):
            ops.remember("windows")
            return "done"
    ops.remember("windows")
    ops.phase("draining")
    return ops.remote("windows")


def _step_off(ops, probe):
    if _already("off", probe):
        return "done"
    if detect(probe) == "windows" or (probe.get("remembered") == "windows" and not probe.get("proxmox") and not probe.get("linux")):
        ops.phase("poweroff")
        return ops.windows_off()
    if not probe.get("proxmox") and not probe.get("linux"):
        return "done"
    ops.phase("draining")
    return ops.remote("off")


def _wait_reply(goal, ops):
    deadline = ops.now() + REPLY_S
    while ops.now() < deadline:
        probe = ops.probe()
        if goal == "windows" and (probe.get("linux") or probe.get("proxmox")) and not probe.get("unit"):
            # Came back as Proxmox. This attempt did not land on Windows.
            pass
        elif reached(goal, probe):
            if goal == "linux":
                ops.remember("")
            return True
        ops.sleep(POLL_S)
    return False


def _wait_until(ops, pred, seconds):
    deadline = ops.now() + seconds
    while ops.now() < deadline:
        if pred(ops.probe()):
            return True
        ops.sleep(POLL_S)
    return pred(ops.probe())


def goal_for(action, probe):
    """Map a button id to linux, windows, or off. None when it is already done."""
    state = detect(probe)
    if action == "os_linux":
        return None if state == "linux" else "linux"
    if action == "os_windows":
        return None if state == "windows" else "windows"
    if action == "gpu_power":
        if state == "off":
            return "linux"
        return "off"
    return None


def start(action):
    """Return True if this process accepted the job. The POST must not wait on SSH."""
    with _mu:
        if _job["running"]:
            return True
    busy = (_remembered().get("job_phase") or "")
    if busy in ("starting", "rebooting", "draining", "waking", "retry", "poweroff"):
        # The box is already off. Windows or Linux should wake it, not sit behind the old power-off.
        if not (busy == "poweroff" and action in ("os_windows", "os_linux")):
            return True
    with _mu:
        if _job["running"]:
            return True
        _job["running"] = True
        _job["target"] = action
        _job["phase"] = "starting"
        _job["error"] = ""
    threading.Thread(target=_worker, args=(action,), daemon=True).start()
    return True


def _worker(action):
    ops = Ops()
    try:
        # Windows is up: reboot it first. Probing the dead Linux VM is a multi-second wait
        # on every tap, and the screen has nothing to show until that probe finishes.
        if action == "os_linux" and ops.windows_to_linux() == "down":
            _set(phase="rebooting", error="")
            if _wait_reply("linux", ops):
                _set(phase="", error="")
                ops.remember("")
                return
            _set(phase="failed", error="no reply")
            return
        probe = ops.probe()
        goal = goal_for(action, probe)
        if goal is None:
            _set(phase="", error="")
            return
        result = run(goal, ops)
        if result == "ok" or result == "already":
            _set(phase="", error="")
            if goal == "windows":
                ops.remember("windows")
            elif goal == "linux":
                ops.remember("")
        elif result == "abort":
            _set(phase="failed", error="quorum abort")
            ops.remember("")
        elif result == "noway":
            _set(phase="failed", error="no windows ssh")
        else:
            _set(phase="failed", error="no reply")
    except Exception as exc:
        _set(phase="failed", error=type(exc).__name__)
    finally:
        with _mu:
            _job["running"] = False


def snapshot(on):
    """Fast state for the GPU tile. Never raises into assemble()."""
    try:
        mem = _remembered()
        age = None
        if mem.get("os_mode_at"):
            age = time.time() - float(mem["os_mode_at"])
        linux = _ssh_ok(LINUX, "echo ok")
        proxmox = False if linux else _ssh_ok(PROXMOX, "echo ok")
        unit = _unit_active() if (linux or proxmox) else False
        windows = bool(WINDOWS) and not linux and _ssh_ok(WINDOWS, "echo ok")
        ping = _ping(PROXMOX_IP) if not linux and not proxmox else False
        with _mu:
            job = _job["running"]
            phase = _job["phase"]
            error = _job["error"]
        if not phase:
            phase = mem.get("job_phase") or ""
            error = error or (mem.get("job_error") or "")
            job = job or bool(phase and phase != "failed")
        probe = {
            "job": job,
            "unit": unit,
            "linux": linux,
            "proxmox": proxmox,
            "windows": windows,
            "ping": ping,
            "remembered": mem.get("os_mode") or "",
            "remembered_age": age,
        }
        if not job and not unit and (linux or (proxmox and probe["remembered"] == "windows")):
            _remember("")
            probe["remembered"] = ""
        state = detect(probe)
        # One missed SSH must not paint a node Kubernetes still sees as off.
        if state == "off" and on and not probe["remembered"]:
            state = "linux"
        # A power-off left behind by a dead collector must not keep the buttons locked
        # once the box is dark.
        with _mu:
            local = _job["running"]
        if not local and phase == "poweroff" and (host_down(probe) or linux or windows):
            phase = ""
            error = ""
            job = False
            probe["job"] = False
            state = "off" if host_down(probe) else detect(probe)
            if state == "off" and on and not probe["remembered"]:
                state = "linux"
            _set(phase="", error="")
        _mark_node(state)
        return {
            "os": state,
            "os_phase": phase if (job or phase == "failed") else ("draining" if unit else ""),
            "os_error": error,
            "os_metrics": bool(linux or (on and state == "linux")),
        }
    except Exception:
        return {"os": "linux" if on else "off", "os_phase": "", "os_error": "", "os_metrics": bool(on)}


def _set(**kwargs):
    with _mu:
        _job.update(kwargs)
        snap = dict(_job)
    try:
        data = _remembered()
        data["job_phase"] = snap.get("phase") or ""
        data["job_error"] = snap.get("error") or ""
        data["job_target"] = snap.get("target") or ""
        from lease import save_os
        save_os(data)
    except Exception:
        return


def _remembered():
    try:
        from lease import load_os
        data = load_os() or {}
    except Exception:
        data = {}
    if data.get("os_mode") or data.get("os_mode_at"):
        return data
    return dict(_mem)


def _mark_node(state):
    """Tell the lifecycle controller this NotReady GPU is Windows on purpose."""
    mode = "windows" if state == "windows" else ""
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if not os.path.exists(token_path):
        return
    if getattr(_mark_node, "last", None) == mode:
        return
    try:
        import httpx
        token = open(token_path).read()
        ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        url = "https://kubernetes.default.svc/api/v1/nodes/racoon-gpu"
        headers = {"Authorization": "Bearer " + token}
        current = httpx.get(url, headers=headers, verify=ca, timeout=4)
        if current.status_code != 200:
            return
        have = ((current.json().get("metadata") or {}).get("annotations") or {}).get("racoon/os-mode") or ""
        if have == mode:
            _mark_node.last = mode
            return
        patch = {"metadata": {"annotations": {"racoon/os-mode": mode or None}}}
        headers["Content-Type"] = "application/merge-patch+json"
        done = httpx.patch(url, headers=headers, verify=ca, json=patch, timeout=4)
        if done.status_code in (200, 201):
            _mark_node.last = mode
    except Exception:
        return


def _remember(mode):
    _mem["os_mode"] = mode or ""
    _mem["os_mode_at"] = time.time() if mode else 0
    try:
        from lease import save_os
        save_os({"os_mode": _mem["os_mode"], "os_mode_at": _mem["os_mode_at"]})
    except Exception:
        pass


def _ssh_ok(target, cmd):
    if not target:
        return False
    try:
        from fetch import ssh_run
        result = ssh_run(target, cmd, timeout=12)
    except Exception:
        return False
    return result is not None and result.returncode == 0


def _ssh_text(target, cmd):
    try:
        from fetch import ssh_run
        result = ssh_run(target, cmd, timeout=12)
    except Exception:
        return ""
    if result is None:
        return ""
    return result.stdout or ""


def _unit_active():
    text = _ssh_text(PROXMOX, "systemctl is-active os-switch 2>/dev/null || true")
    return text.strip() == "active"


def _ping(ip):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _magic(mac):
    raw = mac.replace(":", "").replace("-", "")
    if len(raw) != 12:
        return
    packet = bytes.fromhex("FF" * 6 + raw * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("255.255.255.255", 9))
        sock.sendto(packet, ("192.168.0.255", 9))
    finally:
        sock.close()
