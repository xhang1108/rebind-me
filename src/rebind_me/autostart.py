"""Startup autostart: the elevated bridge scheduled task and the tray Run entry.

The bridge is launched by a per-user scheduled task (trigger
"at log on", highest privileges, ``MultipleInstances=IgnoreNew`` and
``RestartOnFailure`` every minute three times). The tray is launched from the
HKCU ``...\\Run`` key with normal privileges. Both point at ``pythonw.exe`` plus
the ``rebind-me.pyw`` launcher, so no packaged executable is needed.

The task is imported from generated XML because the ``schtasks`` command line
cannot express ``MultipleInstances`` or ``RestartOnFailure``. Nothing here
touches the filesystem or the registry at import time; the defaults are only
constructed when used, and every side effect is injectable for tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence
from xml.sax.saxutils import escape

from .errors import RebindError

TASK_NAME = "RebindMe-Bridge"
TASK_DESCRIPTION = "Rebind Me bridge (elevated, at startup)"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "RebindMe-Tray"
LAUNCHER_NAME = "rebind-me.pyw"

TASK_XML_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# schtasks exit code when the named task does not exist.
_SCHTASKS_NOT_FOUND = 1

# A single schtasks invocation is bounded: the Task Scheduler service can hang
# on a wedged system, which must not freeze the caller indefinitely.
SCHTASKS_TIMEOUT_SECONDS = 15
# Exit code substituted for a timed-out invocation (same convention as timeout(1)).
_SCHTASKS_TIMEOUT = 124


def launcher_paths() -> tuple[str, str]:
    """Return ``(pythonw.exe, rebind-me.pyw)`` absolute paths for this install."""
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    launcher = Path(__file__).resolve().parents[2] / LAUNCHER_NAME
    return str(pythonw), str(launcher)


def role_command(role: str, pythonw: str | None = None, launcher: str | None = None) -> str:
    """Build the quoted command line for ``bridge`` or ``tray``."""
    if pythonw is None or launcher is None:
        default_pythonw, default_launcher = launcher_paths()
        pythonw = pythonw or default_pythonw
        launcher = launcher or default_launcher
    return f'"{pythonw}" "{launcher}" {role}'


def current_user() -> str:
    """Fully-qualified ``DOMAIN\\user`` for the triggering principal."""
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    domain = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME") or ""
    if domain and user:
        return f"{domain}\\{user}"
    return user


def build_task_xml(command: str, user: str, description: str = TASK_DESCRIPTION) -> str:
    """Task Scheduler XML for the elevated, at-startup bridge task."""
    xml_command, arguments = _split_command(command)
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{TASK_XML_NAMESPACE}">\n'
        "  <RegistrationInfo>\n"
        f"    <Description>{escape(description)}</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <LogonTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        f"      <UserId>{escape(user)}</UserId>\n"
        "    </LogonTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"      <UserId>{escape(user)}</UserId>\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>HighestAvailable</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <RestartOnFailure>\n"
        "      <Interval>PT1M</Interval>\n"
        "      <Count>3</Count>\n"
        "    </RestartOnFailure>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(xml_command)}</Command>\n"
        f"      <Arguments>{escape(arguments)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def _split_command(command: str) -> tuple[str, str]:
    """Split a ``"exe" "args"`` command line into command and arguments."""
    text = command.strip()
    if not text:
        raise RebindError("SCHEMA_ERROR", "empty command line")
    if text[0] == '"':
        end = text.find('"', 1)
        if end == -1:
            raise RebindError("SCHEMA_ERROR", "unbalanced quotes in command line")
        return text[1:end], text[end + 1 :].strip()
    command_part, _, arguments = text.partition(" ")
    return command_part, arguments.strip()


def _default_runner(argv: Sequence[str]) -> int:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            creationflags=creationflags,
            check=False,
            timeout=SCHTASKS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _SCHTASKS_TIMEOUT
    return int(result.returncode)


class ScheduledTask:
    """Create, delete and query the bridge task through ``schtasks.exe``."""

    def __init__(self, name: str = TASK_NAME, runner: Callable[[Sequence[str]], int] | None = None):
        self.name = name
        self._run = runner or _default_runner

    def create(self, xml: str) -> None:
        """Import ``xml`` as this task, replacing any existing one."""
        path = self._write_xml(xml)
        try:
            code = self._run(
                ["schtasks", "/Create", "/TN", self.name, "/XML", str(path), "/F"]
            )
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        if code != 0:
            raise RebindError("INTERNAL_ERROR", f"schtasks /Create failed ({code})")

    def delete(self) -> None:
        code = self._run(["schtasks", "/Delete", "/TN", self.name, "/F"])
        if code != 0 and code != _SCHTASKS_NOT_FOUND:
            raise RebindError("INTERNAL_ERROR", f"schtasks /Delete failed ({code})")

    def run_now(self) -> None:
        code = self._run(["schtasks", "/Run", "/TN", self.name])
        if code != 0:
            raise RebindError("INTERNAL_ERROR", f"schtasks /Run failed ({code})")

    def end(self) -> None:
        self._run(["schtasks", "/End", "/TN", self.name])

    def exists(self) -> bool:
        try:
            return self._run(["schtasks", "/Query", "/TN", self.name]) == 0
        except OSError:
            return False

    @staticmethod
    def _write_xml(xml: str) -> Path:
        # schtasks imports the task definition as Unicode (UTF-16 with BOM).
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-16", delete=False
        )
        with handle:
            handle.write(xml)
        return Path(handle.name)


class WindowsRunKey:
    """The HKCU ``...\\Run`` key, wrap-able for tests."""

    def __init__(self, subkey: str = RUN_KEY):
        self.subkey = subkey

    def get(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def set(self, name: str, command: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.subkey) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.subkey, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


class AutostartController:
    """Applies the bridge task and tray Run entry together."""

    def __init__(
        self,
        task: ScheduledTask | None = None,
        run_key: WindowsRunKey | None = None,
        pythonw: str | None = None,
        launcher: str | None = None,
        user: str | None = None,
    ):
        self.task = task or ScheduledTask()
        self.run_key = run_key or WindowsRunKey()
        self.pythonw = pythonw
        self.launcher = launcher
        self.user = user

    def apply(self, enable_bridge: bool, enable_tray: bool) -> dict:
        if enable_bridge:
            command = role_command("bridge", self.pythonw, self.launcher)
            self.task.create(build_task_xml(command, self.user or current_user()))
        else:
            self.task.delete()

        if enable_tray:
            self.run_key.set(
                RUN_VALUE, role_command("tray", self.pythonw, self.launcher)
            )
        else:
            self.run_key.delete(RUN_VALUE)

        return {"bridge": bool(enable_bridge), "tray": bool(enable_tray)}

    def status(self) -> dict:
        return {
            "bridge": self.task.exists(),
            "tray": self.run_key.get(RUN_VALUE) is not None,
        }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI used by ``install.cmd`` / ``uninstall.cmd`` and for debugging.

    ``enable`` installs the elevated bridge task and the tray Run entry,
    ``disable`` removes both, ``status`` prints their presence as JSON.
    """
    import json

    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else "status"
    controller = AutostartController()

    if action == "enable":
        controller.apply(True, True)
        print("bridge task and tray entry installed")
    elif action == "disable":
        controller.apply(False, False)
        print("bridge task and tray entry removed")
    elif action == "status":
        print(json.dumps(controller.status()))
    else:
        print(f"unknown autostart action: {action}", file=sys.stderr)
        return 2
    return 0


__all__ = [
    "AutostartController",
    "LAUNCHER_NAME",
    "RUN_KEY",
    "RUN_VALUE",
    "ScheduledTask",
    "TASK_DESCRIPTION",
    "TASK_NAME",
    "WindowsRunKey",
    "build_task_xml",
    "current_user",
    "launcher_paths",
    "main",
    "role_command",
]
