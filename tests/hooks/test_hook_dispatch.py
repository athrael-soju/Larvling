"""Hook dispatch error tests — empty stdin, invalid JSON across all hook mains."""

import io
import unittest
from unittest import mock


class TestMainDispatchErrors(unittest.TestCase):

    def test_empty_stdin_noop(self):
        from hook_prompt import main as prompt_main
        from hook_stop import main as stop_main
        from hook_end import main as end_main
        for main_fn in (prompt_main, stop_main, end_main):
            with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(b""))):
                main_fn()

    def test_invalid_json_noop(self):
        from hook_prompt import main as prompt_main
        from hook_stop import main as stop_main
        from hook_end import main as end_main
        for main_fn in (prompt_main, stop_main, end_main):
            with mock.patch("sys.stdin", mock.MagicMock(buffer=io.BytesIO(b"not json{{{"))):
                main_fn()
