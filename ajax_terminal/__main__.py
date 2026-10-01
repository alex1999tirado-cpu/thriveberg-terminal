from __future__ import annotations

import importlib.util
import os
import sys


def main() -> int:
    _ensure_standard_streams()
    screenshot_mode = "--screenshot" in sys.argv or "--screenshot-splash" in sys.argv
    _configure_terminal_colors(force=screenshot_mode)
    _migrate_plaintext_settings()
    from ajax_terminal.logging_config import configure_logging

    configure_logging()
    if len(sys.argv) >= 4 and sys.argv[1] == "--gui-chart":
        from ajax_terminal.charts.qt_app import run_chart_app

        kind = sys.argv[2].lower()
        target = sys.argv[3]
        period = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else "1Y"
        interval = sys.argv[5] if len(sys.argv) > 5 and not sys.argv[5].startswith("--") else None
        screenshot = None
        if "--screenshot" in sys.argv:
            index = sys.argv.index("--screenshot")
            screenshot = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
        return run_chart_app(kind, target, period, interval, screenshot=screenshot)
    if len(sys.argv) >= 3 and sys.argv[1] == "--chart":
        from ajax_terminal.charts.qt_app import run_chart_app

        symbol = sys.argv[2]
        period = sys.argv[3] if len(sys.argv) > 3 else "1Y"
        interval = sys.argv[4] if len(sys.argv) > 4 else None
        return run_chart_app("price", symbol, period, interval)
    terminal_mode = "--terminal" in sys.argv
    initial_command = None
    if "--command" in sys.argv:
        index = sys.argv.index("--command")
        initial_command = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
    screenshot = None
    if "--screenshot" in sys.argv:
        index = sys.argv.index("--screenshot")
        screenshot = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
    splash_screenshot = None
    if "--screenshot-splash" in sys.argv:
        index = sys.argv.index("--screenshot-splash")
        splash_screenshot = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
    if not terminal_mode and importlib.util.find_spec("PySide6") is not None:
        from ajax_terminal.desktop_app import run_desktop_app

        return run_desktop_app(
            initial_command=initial_command,
            screenshot=screenshot,
            splash_screenshot=splash_screenshot,
        )
    missing = [package for package in ("textual", "rich") if importlib.util.find_spec(package) is None]
    if missing:
        print("THRIVEBERG Terminal needs Textual/Rich for the TUI.")
        print("Install dependencies with:")
        print('  python -m pip install -e ".[dev]"')
        print(f"Missing: {', '.join(missing)}")
        return 1
    from ajax_terminal.app import AjaxTerminalApp

    app = AjaxTerminalApp(startup_command=initial_command)
    app.run()
    return 0


def _migrate_plaintext_settings() -> None:
    """Remove recognized API keys from legacy .env files after DPAPI migration."""
    try:
        from ajax_terminal.config import application_roots
        from ajax_terminal.secure_settings import migrate_env_file

        seen: set[str] = set()
        for root in application_roots():
            env_path = root / ".env"
            key = os.path.normcase(str(env_path))
            if key in seen or not env_path.is_file():
                continue
            seen.add(key)
            migrate_env_file(env_path)
    except Exception:
        # A read-only legacy location must never prevent the terminal from starting.
        return


def _ensure_standard_streams() -> None:
    """Provide harmless streams when a Windows GUI executable has no console."""
    frozen_windows_app = os.name == "nt" and bool(getattr(sys, "frozen", False))
    for name in ("stdout", "stderr"):
        if frozen_windows_app:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            continue
        stream = getattr(sys, name, None)
        try:
            if stream is None or getattr(stream, "closed", False):
                raise OSError(f"{name} is closed")
            stream.write("")
            stream.flush()
        except (AttributeError, OSError, RuntimeError, ValueError):
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _configure_terminal_colors(*, force: bool = False) -> None:
    """Undo color-suppression inherited from non-interactive Windows launchers."""
    stdout = sys.stdout
    if os.name != "nt":
        return
    if not force and (stdout is None or not hasattr(stdout, "isatty") or not stdout.isatty()):
        return
    os.environ.pop("NO_COLOR", None)
    if os.environ.get("TERM", "").lower() in {"", "dumb"}:
        os.environ["TERM"] = "xterm-256color"
    os.environ.setdefault("COLORTERM", "truecolor")
    os.environ.setdefault("FORCE_COLOR", "1")


if __name__ == "__main__":
    raise SystemExit(main())
