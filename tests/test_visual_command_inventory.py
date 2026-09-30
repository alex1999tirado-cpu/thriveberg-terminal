from ajax_terminal.ui.commands.parser import ALIASES, CommandAction
from ajax_terminal.ui.commands.visuals import COMMAND_VISUAL_FAMILY, visual_family_for


def test_every_command_has_a_visual_family() -> None:
    assert set(COMMAND_VISUAL_FAMILY) == set(CommandAction)


def test_every_alias_resolves_to_an_audited_visual_family() -> None:
    assert all(visual_family_for(action) for action in ALIASES.values())
