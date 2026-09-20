"""Tests for logon autostart (scheduled task XML and HKCU Run)."""

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

from rebind_me import autostart
from rebind_me.autostart import (
    RUN_VALUE,
    AutostartController,
    ScheduledTask,
    WindowsRunKey,
    build_task_xml,
    current_user,
    role_command,
)


class TaskXmlTest(unittest.TestCase):
    def test_core_settings_present(self) -> None:
        xml = build_task_xml('"C:\\Py\\pythonw.exe" "C:\\app\\rebind-me.pyw" bridge', "PC\\me")
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn("<RunLevel>HighestAvailable</RunLevel>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("<Interval>PT1M</Interval>", xml)
        self.assertIn("<Count>3</Count>", xml)
        self.assertIn("<UserId>PC\\me</UserId>", xml)
        self.assertIn("<Command>C:\\Py\\pythonw.exe</Command>", xml)
        self.assertIn('<Arguments>"C:\\app\\rebind-me.pyw" bridge</Arguments>', xml)

    def test_special_characters_are_escaped(self) -> None:
        xml = build_task_xml('"C:\\a&b\\pythonw.exe" "launcher" bridge', "D&O\\user")
        self.assertIn("C:\\a&amp;b\\pythonw.exe", xml)
        self.assertIn("D&amp;O\\user", xml)
        self.assertNotIn("a&b", xml)

    def test_rejects_unbalanced_quotes(self) -> None:
        with self.assertRaises(Exception):
            build_task_xml('"unterminated bridge', "PC\\me")


class RoleCommandTest(unittest.TestCase):
    def test_quotes_paths(self) -> None:
        command = role_command("tray", "C:\\Py\\pythonw.exe", "C:\\app\\rebind-me.pyw")
        self.assertEqual(command, '"C:\\Py\\pythonw.exe" "C:\\app\\rebind-me.pyw" tray')

    def test_current_user_is_non_empty(self) -> None:
        self.assertTrue(current_user())


class FakeRunner:
    def __init__(self, codes=None) -> None:
        self.calls: list[list[str]] = []
        self.codes = codes or {}
        self.last_xml: str | None = None

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[1] == "/Create":
            xml_path = Path(argv[argv.index("/XML") + 1])
            self.last_xml = xml_path.read_text(encoding="utf-16")
        return self.codes.get(argv[1], 0)


class ScheduledTaskTest(unittest.TestCase):
    def test_create_imports_utf16_xml(self) -> None:
        runner = FakeRunner()
        task = ScheduledTask("RebindMe-Test", runner=runner)
        task.create(build_task_xml('"py" "launcher" bridge', "PC\\me"))
        argv = runner.calls[0]
        self.assertEqual(argv[:3], ["schtasks", "/Create", "/TN"])
        self.assertIn("/F", argv)
        self.assertIsNotNone(runner.last_xml)
        self.assertIn("LogonTrigger", runner.last_xml)

    def test_delete_tolerates_no_task(self) -> None:
        runner = FakeRunner({"/Delete": 1})
        ScheduledTask("RebindMe-Test", runner=runner).delete()  # must not raise

    def test_delete_raises_on_other_failure(self) -> None:
        runner = FakeRunner({"/Delete": 5})
        with self.assertRaises(Exception):
            ScheduledTask("RebindMe-Test", runner=runner).delete()

    def test_run_now_argv(self) -> None:
        runner = FakeRunner()
        ScheduledTask("RebindMe-Test", runner=runner).run_now()
        self.assertEqual(runner.calls[0], ["schtasks", "/Run", "/TN", "RebindMe-Test"])

    def test_exists_follows_exit_code(self) -> None:
        self.assertTrue(ScheduledTask("t", runner=FakeRunner({"/Query": 0})).exists())
        self.assertFalse(ScheduledTask("t", runner=FakeRunner({"/Query": 1})).exists())


class FakeTask:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted = 0
        self.present = False

    def create(self, xml: str) -> None:
        self.created.append(xml)
        self.present = True

    def delete(self) -> None:
        self.deleted += 1
        self.present = False

    def exists(self) -> bool:
        return self.present


class FakeRunKey:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, command: str) -> None:
        self.values[name] = command

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class AutostartControllerTest(unittest.TestCase):
    def make(self):
        task, run_key = FakeTask(), FakeRunKey()
        controller = AutostartController(
            task=task,
            run_key=run_key,
            pythonw="C:\\Py\\pythonw.exe",
            launcher="C:\\app\\rebind-me.pyw",
            user="PC\\me",
        )
        return controller, task, run_key

    def test_enable_both(self) -> None:
        controller, task, run_key = self.make()
        result = controller.apply(True, True)
        self.assertEqual(result, {"bridge": True, "tray": True})
        self.assertIn("rebind-me.pyw\" bridge", task.created[0])
        self.assertIn("rebind-me.pyw\" tray", run_key.values[RUN_VALUE])

    def test_disable_both(self) -> None:
        controller, task, run_key = self.make()
        controller.apply(True, True)
        result = controller.apply(False, False)
        self.assertEqual(result, {"bridge": False, "tray": False})
        self.assertEqual(task.deleted, 1)
        self.assertNotIn(RUN_VALUE, run_key.values)

    def test_status_reflects_state(self) -> None:
        controller, task, run_key = self.make()
        self.assertEqual(controller.status(), {"bridge": False, "tray": False})
        controller.apply(True, True)
        self.assertEqual(controller.status(), {"bridge": True, "tray": True})


@unittest.skipIf(winreg is None, "Windows registry only")
class WindowsRunKeyTest(unittest.TestCase):
    SUBKEY = r"Software\RebindMe\Test"

    def tearDown(self) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.SUBKEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, "probe")
        except FileNotFoundError:
            pass

    def test_set_get_delete_round_trip(self) -> None:
        run_key = WindowsRunKey(self.SUBKEY)
        self.assertIsNone(run_key.get("probe"))
        run_key.set("probe", '"py" "launcher" tray')
        self.assertEqual(run_key.get("probe"), '"py" "launcher" tray')
        run_key.delete("probe")
        self.assertIsNone(run_key.get("probe"))
        run_key.delete("probe")  # idempotent


class DefaultRunnerTest(unittest.TestCase):
    def test_run_is_bounded_by_timeout(self) -> None:
        completed = mock.Mock(returncode=0)
        with mock.patch.object(autostart.subprocess, "run", return_value=completed) as run:
            self.assertEqual(autostart._default_runner(["schtasks", "/Query"]), 0)
        self.assertEqual(
            run.call_args.kwargs["timeout"], autostart.SCHTASKS_TIMEOUT_SECONDS
        )

    def test_timeout_maps_to_a_failure_code(self) -> None:
        with mock.patch.object(
            autostart.subprocess,
            "run",
            side_effect=autostart.subprocess.TimeoutExpired("schtasks", 15),
        ):
            code = autostart._default_runner(["schtasks", "/Query"])
        self.assertEqual(code, autostart._SCHTASKS_TIMEOUT)
        # A timeout must be a failure for the callers that check non-zero.
        self.assertNotEqual(code, 0)
        self.assertNotEqual(code, autostart._SCHTASKS_NOT_FOUND)


class MainCliTest(unittest.TestCase):
    class FakeController:
        def __init__(self) -> None:
            self.applied: list[tuple] = []

        def apply(self, bridge: bool, tray: bool) -> dict:
            self.applied.append((bridge, tray))
            return {"bridge": bridge, "tray": tray}

        def status(self) -> dict:
            return {"bridge": True, "tray": False}

    def test_enable_disable_and_status_default(self) -> None:
        fake = self.FakeController()
        out = io.StringIO()
        with mock.patch.object(autostart, "AutostartController", return_value=fake):
            with contextlib.redirect_stdout(out):
                self.assertEqual(autostart.main(["enable"]), 0)
                self.assertEqual(autostart.main(["disable"]), 0)
                self.assertEqual(autostart.main([]), 0)
        self.assertEqual(fake.applied, [(True, True), (False, False)])
        self.assertIn('"bridge": true', out.getvalue())

    def test_unknown_action_exits_two(self) -> None:
        err = io.StringIO()
        with mock.patch.object(autostart, "AutostartController", return_value=self.FakeController()):
            with contextlib.redirect_stderr(err):
                self.assertEqual(autostart.main(["frobnicate"]), 2)
        self.assertIn("unknown autostart action", err.getvalue())


if __name__ == "__main__":
    unittest.main()
