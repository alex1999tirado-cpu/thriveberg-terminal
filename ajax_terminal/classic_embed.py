from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

from rich.console import Console
from rich.terminal_theme import TerminalTheme

from ajax_terminal.app import AjaxTerminalApp
from ajax_terminal.models.quote import Quote
from ajax_terminal.services.social_service import SocialService
from ajax_terminal.ui.commands.parser import CommandAction


@dataclass(frozen=True, slots=True)
class ClassicAction:
    row: int
    column_start: int
    column_end: int
    action: str


@dataclass(frozen=True, slots=True)
class ClassicSnapshot:
    command: str
    action: CommandAction
    svg: str
    quote: Quote | None = None
    columns: int = 0
    rows: int = 0
    actions: tuple[ClassicAction, ...] = ()


_EMBEDDED_SVG_FORMAT = """\
<svg class="thriveberg-terminal" viewBox="0 0 {terminal_width} {terminal_height}"
     preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
  <style>
    .{unique_id}-matrix {{
      font-family: "DejaVu Sans Mono", Consolas, monospace;
      font-size: {char_height}px;
      line-height: {line_height}px;
      font-variant-east-asian: full-width;
    }}
    {styles}
  </style>
  <defs>{lines}</defs>
  <rect x="0" y="0" width="{terminal_width}" height="{terminal_height}" fill="#030404"/>
  {backgrounds}
  <g class="{unique_id}-matrix">{matrix}</g>
</svg>
"""

_THRIVEBERG_TERMINAL_THEME = TerminalTheme(
    background=(3, 4, 4),
    foreground=(215, 215, 215),
    normal=[
        (3, 4, 4),
        (196, 48, 72),
        (86, 176, 82),
        (217, 145, 22),
        (79, 158, 187),
        (166, 110, 134),
        (215, 215, 215),
        (205, 207, 201),
    ],
    bright=[
        (82, 86, 84),
        (255, 49, 95),
        (98, 230, 0),
        (255, 176, 0),
        (93, 178, 207),
        (199, 139, 163),
        (245, 245, 241),
        (245, 245, 241),
    ],
)


def render_classic_snapshot(
    command: str,
    social_service: SocialService | None = None,
    *,
    columns: int = 190,
    rows: int = 50,
) -> ClassicSnapshot:
    return asyncio.run(
        _render_classic_snapshot(
            command,
            social_service,
            columns=max(100, columns),
            rows=max(30, rows),
        )
    )


async def _render_classic_snapshot(
    command: str,
    social_service: SocialService | None,
    *,
    columns: int,
    rows: int,
) -> ClassicSnapshot:
    app = AjaxTerminalApp(social_service=social_service, startup_command=command)
    async with app.run_test(size=(columns, rows)) as pilot:
        await pilot.pause()
        for selector in (
            "#topbar",
            "#instrument-strip",
            "#command",
            "#command-suggestions",
            "#hotkeys",
        ):
            app.query_one(selector).display = False
        await pilot.pause()
        svg, actions = _export_embedded_svg(app, simplify=True)
        return ClassicSnapshot(
            command=command,
            action=app.current_command.action,
            svg=svg,
            quote=app._active_quote,
            columns=columns,
            rows=rows,
            actions=actions,
        )


def _export_embedded_svg(
    app: AjaxTerminalApp,
    *,
    simplify: bool,
) -> tuple[str, tuple[ClassicAction, ...]]:
    width, height = app.size
    console = Console(
        width=width,
        height=height,
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
        record=True,
        legacy_windows=False,
        safe_box=False,
    )
    screen_render = app.screen._compositor.render_update(
        full=True,
        screen_stack=app._background_screens,
        simplify=simplify,
    )
    console.print(screen_render)
    actions = _screen_actions(app)
    return (
        console.export_svg(
            title="",
            theme=_THRIVEBERG_TERMINAL_THEME,
            code_format=_EMBEDDED_SVG_FORMAT,
            font_aspect_ratio=0.61,
        ),
        actions,
    )


def _screen_actions(app: AjaxTerminalApp) -> tuple[ClassicAction, ...]:
    width, height = app.size
    actions: list[ClassicAction] = []
    for row in range(height):
        active_action: str | None = None
        start = 0
        for column in range(width + 1):
            if column < width:
                style = app.screen.get_style_at(column, row)
                action = str(style.meta.get("@click")) if style.meta.get("@click") else None
            else:
                action = None
            if action == active_action:
                continue
            if active_action is not None:
                actions.append(ClassicAction(row, start, column, active_action))
            active_action = action
            start = column
    return tuple(actions)
