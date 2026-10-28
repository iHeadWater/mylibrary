"""A real child process proves stderr is decoded by the ladder, stdout stays UTF-8.

The child writes raw CP936 bytes to ``stderr.buffer`` -- exactly what a Windows
program does when it reports an error in the active code page -- and a UTF-8
JSONL event to stdout.
"""
from __future__ import annotations

import json
import sys
import unittest
from unittest.mock import patch

from hydrolitagent.cards.card_generators.streaming import run_streaming_prompt

CP936_MESSAGE = "错误：文件不存在"

SCRIPT = (
    "import json, sys\n"
    f"sys.stderr.buffer.write({CP936_MESSAGE!r}.encode('gbk'))\n"
    "sys.stderr.buffer.flush()\n"
    "print(json.dumps({'type': 'turn.completed', 'note': '中文'}), flush=True)\n"
)


class StreamingDecodingTests(unittest.TestCase):
    def run_child(self):
        # Patch the ladder's locale lookup so the assertion does not depend on
        # the host's code page.
        with patch(
            "hydrolitagent.cards.infrastructure.decoding.locale.getpreferredencoding",
            return_value="gbk",
        ):
            return run_streaming_prompt(
                [sys.executable, "-u", "-c", SCRIPT],
                "",
                10,
                {"PYTHONIOENCODING": "utf-8"},
            )

    def test_cp936_stderr_is_readable_and_stdout_stays_utf8_jsonl(self):
        result = self.run_child()

        self.assertEqual(result.returncode, 0)
        event = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(event, {"type": "turn.completed", "note": "中文"})
        self.assertIn(CP936_MESSAGE, result.stderr)
        self.assertNotIn("�", result.stderr)
        self.assertEqual(result.stderr_meta.encoding, "locale:gbk")
        self.assertEqual(result.stderr_meta.replacement_count, 0)


if __name__ == "__main__":
    unittest.main()
