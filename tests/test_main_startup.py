from __future__ import annotations

import io

import ajax_terminal.__main__ as entrypoint


class _UnwritableStream:
    closed = False

    def write(self, _value: str) -> None:
        raise RuntimeError("stdout is closed")

    def flush(self) -> None:
        raise RuntimeError("stdout is closed")


def test_windowed_executable_receives_writable_standard_streams(monkeypatch) -> None:
    closed_stderr = io.StringIO()
    closed_stderr.close()
    monkeypatch.setattr(entrypoint.sys, "stdout", _UnwritableStream())
    monkeypatch.setattr(entrypoint.sys, "stderr", closed_stderr)

    entrypoint._ensure_standard_streams()

    assert entrypoint.sys.stdout is not None
    assert entrypoint.sys.stderr is not None
    assert not entrypoint.sys.stdout.closed
    assert not entrypoint.sys.stderr.closed
    entrypoint.sys.stdout.close()
    entrypoint.sys.stderr.close()


def test_terminal_color_setup_accepts_windowed_executable_without_stdout(monkeypatch) -> None:
    monkeypatch.setattr(entrypoint.os, "name", "nt")
    monkeypatch.setattr(entrypoint.sys, "stdout", None)

    entrypoint._configure_terminal_colors()
