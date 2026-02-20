"""Transcript parsing tests — strip_ide_tags, _is_real_user_message, parse_last_turn."""

import json
import os
import tempfile
import unittest

from conftest import make_db, setup_test_db


class TestTranscriptParsing(unittest.TestCase):

    def test_strip_ide_tags_basic(self):
        from transcript import strip_ide_tags
        text = '<ide_opened_file>/path/to/file.py</ide_opened_file> hello world'
        self.assertEqual(strip_ide_tags(text), "hello world")

    def test_strip_ide_tags_selection(self):
        from transcript import strip_ide_tags
        text = '<ide_selection>some selected text</ide_selection> actual prompt'
        self.assertEqual(strip_ide_tags(text), "actual prompt")

    def test_strip_ide_tags_multiple(self):
        from transcript import strip_ide_tags
        text = (
            '<ide_opened_file>file1.py</ide_opened_file> '
            '<ide_selection>sel</ide_selection> prompt here'
        )
        self.assertEqual(strip_ide_tags(text), "prompt here")

    def test_strip_ide_tags_preserves_content(self):
        from transcript import strip_ide_tags
        self.assertEqual(strip_ide_tags("just a normal prompt"), "just a normal prompt")

    def test_strip_ide_tags_empty(self):
        from transcript import strip_ide_tags
        self.assertEqual(strip_ide_tags(""), "")

    def test_is_real_user_message_text(self):
        from transcript import _is_real_user_message
        self.assertTrue(_is_real_user_message(
            {"type": "user", "message": {"content": "hello"}}))

    def test_is_real_user_message_tool_result(self):
        from transcript import _is_real_user_message
        self.assertFalse(_is_real_user_message(
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}))

    def test_is_real_user_message_non_user(self):
        from transcript import _is_real_user_message
        self.assertFalse(_is_real_user_message(
            {"type": "assistant", "message": {"content": "hi"}}))

    def test_is_real_user_message_list_without_tool_result(self):
        from transcript import _is_real_user_message
        self.assertTrue(_is_real_user_message(
            {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}))

    def test_parse_last_turn_empty(self):
        from transcript import parse_last_turn
        text, tools = parse_last_turn(None)
        self.assertIsNone(text)
        self.assertEqual(tools, {})

    def test_parse_last_turn_nonexistent(self):
        from transcript import parse_last_turn
        text, tools = parse_last_turn("/nonexistent/path.jsonl")
        self.assertIsNone(text)
        self.assertEqual(tools, {})

    def test_parse_last_turn_simple(self):
        from transcript import parse_last_turn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "do something"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I did it"}]}}) + "\n")
            path = f.name
        try:
            text, tools = parse_last_turn(path)
            self.assertEqual(text, "I did it")
            self.assertEqual(tools, {})
        finally:
            os.unlink(path)

    def test_parse_last_turn_with_tools(self):
        from transcript import parse_last_turn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "read file"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Read"},
                {"type": "text", "text": "Here's the file"},
            ]}}) + "\n")
            path = f.name
        try:
            text, tools = parse_last_turn(path)
            self.assertEqual(text, "Here's the file")
            self.assertEqual(tools, {"Read": 2})
        finally:
            os.unlink(path)

    def test_parse_last_turn_skips_tool_results(self):
        from transcript import parse_last_turn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "do work"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working..."}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "file contents"}]}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "All done"}]}}) + "\n")
            path = f.name
        try:
            text, tools = parse_last_turn(path)
            self.assertIn("All done", text)
            self.assertIn("Working", text)
        finally:
            os.unlink(path)
