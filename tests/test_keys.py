"""Tests for key code tables and classification."""

import unittest

from rebind_me import keys


class KeyCodeTest(unittest.TestCase):
    def test_letters_and_digits(self) -> None:
        self.assertEqual(keys.VK_CODES["KeyA"], 0x41)
        self.assertEqual(keys.VK_CODES["KeyZ"], 0x5A)
        self.assertEqual(keys.VK_CODES["Digit0"], 0x30)
        self.assertEqual(keys.VK_CODES["Digit9"], 0x39)

    def test_function_keys(self) -> None:
        self.assertEqual(keys.VK_CODES["F1"], 0x70)
        self.assertEqual(keys.VK_CODES["F12"], 0x7B)

    def test_named_keys(self) -> None:
        for name in ("ControlLeft", "ShiftRight", "ArrowUp", "Delete", "Escape"):
            self.assertIn(name, keys.VK_CODES)

    def test_classification(self) -> None:
        self.assertTrue(keys.is_keyboard_code("KeyK"))
        self.assertFalse(keys.is_keyboard_code("MouseLeft"))
        self.assertTrue(keys.is_mouse_code("MouseLeft"))
        self.assertTrue(keys.is_scroll_code("ScrollUp"))
        self.assertFalse(keys.is_valid_code("Nope"))

    def test_modifiers_and_extended(self) -> None:
        self.assertIn("ControlLeft", keys.MODIFIER_KEY_CODES)
        self.assertIn("ArrowLeft", keys.EXTENDED_CODES)

    def test_hook_reverse_lookup_skips_numpad_enter(self) -> None:
        self.assertNotEqual(keys.HOOK_CODES_BY_VK[0x0D], "NumpadEnter")


if __name__ == "__main__":
    unittest.main()
