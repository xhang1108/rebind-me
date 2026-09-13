"""Tests for the singleton mutex and rotating log setup."""

import tempfile
import unittest
from pathlib import Path

from rebind_me import logsetup
from rebind_me.winapi.mutex import SingleInstance


class SingleInstanceTest(unittest.TestCase):
    def test_second_acquire_fails_until_released(self) -> None:
        name = "Global\\RebindMe-Test-SingleInstance"
        first = SingleInstance(name)
        second = SingleInstance(name)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        third = SingleInstance(name)
        self.assertTrue(third.acquire())
        third.release()


class LoggingTest(unittest.TestCase):
    def test_writes_to_rotating_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = logsetup.setup_logging(Path(tmp), "debug")
            try:
                logger.info("hello")
                for handler in logger.handlers:
                    handler.flush()
                log_file = Path(tmp) / logsetup.LOG_FILENAME
                self.assertTrue(log_file.exists())
                self.assertIn("hello", log_file.read_text(encoding="utf-8"))
            finally:
                for handler in list(logger.handlers):
                    handler.close()
                logger.handlers.clear()


if __name__ == "__main__":
    unittest.main()
