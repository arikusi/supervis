"""Tests for supervisor.widgets.output_log module."""

from supervisor.widgets.output_log import OutputLog


class TestDeepSeekBuffering:
    def test_token_accumulates_in_buffer(self):
        log = OutputLog()
        log.write_deepseek_start()
        log.write_deepseek_token("hello ")
        log.write_deepseek_token("world")
        assert log._ds_buffer == "hello world"

    def test_reasoning_accumulates_in_buffer(self):
        log = OutputLog()
        log.write_deepseek_start()
        log.write_deepseek_reasoning("thinking ")
        log.write_deepseek_reasoning("hard")
        assert log._reasoning_buffer == "thinking hard"

    def test_start_resets_buffers(self):
        log = OutputLog()
        log._ds_buffer = "leftover"
        log._reasoning_buffer = "old reasoning"
        log.write_deepseek_start()
        assert log._ds_buffer == ""
        assert log._reasoning_buffer == ""

    def test_done_clears_buffers(self):
        log = OutputLog()
        log.write_deepseek_start()
        log.write_deepseek_token("content")
        log.write_deepseek_reasoning("thinking")
        log.write_deepseek_done("$0.0001")
        assert log._ds_buffer == ""
        assert log._reasoning_buffer == ""
