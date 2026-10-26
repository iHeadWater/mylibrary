"""The child-process decoding ladder: UTF-8, then the locale, then replace."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from hydrolitagent.cards.infrastructure.decoding import (
    DecodedText,
    decode_process_output,
    decode_text,
)

CP936_MESSAGE = "错误：文件不存在"


class DecodeProcessOutputTests(unittest.TestCase):
    def test_utf8_chinese_is_decoded_as_utf8_without_replacements(self):
        data = CP936_MESSAGE.encode("utf-8")

        decoded = decode_process_output(data)

        self.assertEqual(decoded, DecodedText(CP936_MESSAGE, "utf-8", 0))

    def test_cp936_falls_back_to_the_locale_without_replacement(self):
        data = CP936_MESSAGE.encode("gbk")
        with self.assertRaises(UnicodeDecodeError):
            data.decode("utf-8")  # non-vacuity: the UTF-8 branch must fail first

        with patch(
            "hydrolitagent.cards.infrastructure.decoding.locale.getpreferredencoding",
            return_value="gbk",
        ):
            decoded = decode_process_output(data)

        self.assertEqual(decoded.text, CP936_MESSAGE)
        self.assertEqual(decoded.encoding, "locale:gbk")
        self.assertEqual(decoded.replacement_count, 0)
        self.assertNotIn("�", decoded.text)

    def test_preferred_overrides_the_process_locale(self):
        data = CP936_MESSAGE.encode("gbk")

        decoded = decode_process_output(data, preferred="gbk")

        self.assertEqual(decoded.text, CP936_MESSAGE)
        self.assertEqual(decoded.encoding, "locale:gbk")

    def test_invalid_bytes_are_replaced_and_counted(self):
        # 0xFF is not valid UTF-8 and not a valid GBK lead byte either.
        decoded = decode_process_output(b"\xff\xfe\x00", preferred="gbk")

        self.assertEqual(decoded.encoding, "replace")
        self.assertGreater(decoded.replacement_count, 0)
        self.assertEqual(decoded.text.count("�"), decoded.replacement_count)

    def test_utf8_locale_does_not_become_a_locale_match(self):
        with patch(
            "hydrolitagent.cards.infrastructure.decoding.locale.getpreferredencoding",
            return_value="utf-8",
        ):
            decoded = decode_process_output(b"\xff")

        self.assertEqual(decoded.encoding, "replace")
        self.assertGreater(decoded.replacement_count, 0)

    def test_empty_input_has_its_own_encoding_label(self):
        for value in (None, b""):
            with self.subTest(value=value):
                self.assertEqual(
                    decode_process_output(value), DecodedText("", "empty", 0)
                )


class DecodeTextTests(unittest.TestCase):
    def test_text_passes_through(self):
        self.assertEqual(decode_text("already text"), "already text")

    def test_bytes_use_the_ladder(self):
        with patch(
            "hydrolitagent.cards.infrastructure.decoding.locale.getpreferredencoding",
            return_value="gbk",
        ):
            self.assertEqual(decode_text(CP936_MESSAGE.encode("gbk")), CP936_MESSAGE)

    def test_none_becomes_empty_string(self):
        self.assertEqual(decode_text(None), "")


if __name__ == "__main__":
    unittest.main()
