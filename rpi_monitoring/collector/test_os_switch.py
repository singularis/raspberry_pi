"""OS switch decisions. No SSH, no clock waiting on the real 10 minutes."""

from os_switch import detect, goal_for, reached, run


class Fake:
    def __init__(self):
        self.t = 0.0
        self.linux = False
        self.proxmox = False
        self.windows = False
        self.ping = False
        self.unit = False
        self.remembered = ""
        self.calls = []
        self.remote_result = "down"
        self.linux_on_second_wol = False

    def probe(self):
        return {
            "job": False,
            "unit": self.unit,
            "linux": self.linux,
            "proxmox": self.proxmox,
            "windows": self.windows,
            "ping": self.ping,
            "remembered": self.remembered,
            "remembered_age": 0 if self.remembered else None,
        }

    def wol(self):
        self.calls.append("wol")

    def remote(self, mode):
        self.calls.append("remote:" + mode)
        if mode == "windows":
            self.linux = False
            self.proxmox = False
        if mode == "off":
            self.linux = False
            self.proxmox = False
        return self.remote_result

    def windows_to_linux(self):
        self.calls.append("win2lin")
        return "noway"

    def windows_off(self):
        self.calls.append("winoff")
        return "noway"

    def sleep(self, seconds):
        self.t += seconds
        if self.linux_on_second_wol and self.calls.count("wol") >= 2 and self.t > 700:
            self.linux = True
            self.proxmox = True

    def now(self):
        return self.t

    def phase(self, text):
        self.calls.append("phase:" + text)

    def remember(self, mode):
        self.remembered = mode or ""


def test_poweroff_is_done_when_nothing_answers():
    assert reached("off", {"job": True}) is True
    assert reached("off", {"job": True, "ping": True}) is False


def test_detect_order():
    assert detect({"linux": True, "proxmox": True}) == "linux"
    assert detect({"proxmox": True}) == "proxmox"
    assert detect({"remembered": "windows", "remembered_age": 10}) == "windows"
    assert detect({"remembered": "windows", "remembered_age": 1000, "ping": True}) == "windows"
    assert detect({"remembered": "windows", "remembered_age": 1000}) == "off"
    assert detect({}) == "off"
    assert detect({"job": True, "linux": True}) == "switching"


def test_power_on_from_off_retries_wol_once():
    ops = Fake()
    ops.linux_on_second_wol = True
    assert run("linux", ops) == "ok"
    assert ops.calls.count("wol") == 2
    assert not any(c.startswith("remote:") for c in ops.calls)


def test_linux_already_up_does_not_wol():
    ops = Fake()
    ops.linux = True
    ops.proxmox = True
    assert run("linux", ops) == "already"
    assert ops.calls == []


def test_windows_from_linux_retries_once_when_proxmox_returns():
    ops = Fake()
    ops.linux = True
    ops.proxmox = True

    def remote(mode):
        ops.calls.append("remote:" + mode)
        # Reboot did not stick: Proxmox is still the machine we can see.
        ops.linux = False
        ops.proxmox = True
        ops.ping = False
        return "done"

    ops.remote = remote
    assert run("windows", ops) == "no reply"
    assert ops.calls.count("remote:windows") == 2


def test_windows_answers_on_ping():
    ops = Fake()
    ops.linux = True
    ops.proxmox = True

    def remote(mode):
        ops.calls.append("remote:" + mode)
        ops.linux = False
        ops.proxmox = False
        ops.ping = True
        return "down"

    ops.remote = remote
    assert run("windows", ops) == "ok"
    assert ops.calls.count("remote:windows") == 1
    assert reached("windows", ops.probe())


def test_quorum_abort_is_not_retried():
    ops = Fake()
    ops.linux = True
    ops.proxmox = True
    ops.remote_result = "abort"
    assert run("windows", ops) == "abort"
    assert ops.calls.count("remote:windows") == 1


def test_windows_power_without_ssh_does_not_wake():
    ops = Fake()
    ops.remembered = "windows"
    ops.ping = True
    assert run("off", ops) == "noway"
    assert ops.calls.count("wol") == 0
    assert "winoff" in ops.calls


def test_goal_for_buttons():
    off = {}
    linux = {"linux": True, "proxmox": True}
    assert goal_for("gpu_power", off) == "linux"
    assert goal_for("gpu_power", linux) == "off"
    assert goal_for("os_linux", linux) is None
    assert goal_for("os_windows", linux) == "windows"
    assert goal_for("os_windows", {"remembered": "windows", "ping": True}) is None


def test_windows_off_falls_back_to_shutdown():
    from os_switch import windows_off_commands
    cmds = windows_off_commands()
    assert "poweroff.ps1" in cmds[0]
    assert cmds[1] == "shutdown /s /t 0 /f"


def test_nightly_windows_off_is_after_22():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from os_switch import nightly_due
    london = ZoneInfo("Europe/London")
    ten = datetime(2026, 11, 9, 22, 0, tzinfo=london)
    before = datetime(2026, 11, 9, 21, 59, tzinfo=london)
    assert nightly_due(ten, "windows", "")
    assert not nightly_due(before, "windows", "")
    assert not nightly_due(ten, "linux", "")
    assert nightly_due(ten, "windows", "2026-11-09")
