from __future__ import annotations

import asyncio

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from ajax_terminal.models.social import FriendConnection, FriendshipStatus, SocialUser
from ajax_terminal.services.social_service import SocialService


class SocialWorkspace(Vertical):
    can_focus = True

    def __init__(self, service: SocialService, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.service = service
        self.search_results: list[SocialUser] = []
        self.connections: list[FriendConnection] = []
        self.selected_user: SocialUser | None = None
        self.share_command = ""

    def compose(self) -> ComposeResult:
        yield Static("THRIVEBERG SOCIAL | OFFLINE", id="social-status")
        with Vertical(id="social-setup"):
            yield Static("CONNECT SOCIAL SERVER", classes="social-section-title")
            yield Input(placeholder="SUPABASE PROJECT URL", id="social-server-url")
            yield Input(placeholder="SUPABASE PUBLISHABLE KEY", id="social-server-key")
            with Horizontal(classes="social-button-row"):
                yield Button("SAVE & CONNECT", id="social-connect-server", classes="social-action")
            yield Static(
                "Use the shared project's publishable key. Secret and service_role keys are rejected.",
                id="social-setup-note",
            )
        with Horizontal(id="social-auth"):
            with Vertical(id="social-auth-form"):
                yield Static("SIGN IN / CREATE ACCOUNT", classes="social-section-title")
                yield Input(placeholder="EMAIL", id="social-email")
                yield Input(placeholder="PASSWORD", password=True, id="social-password")
                yield Input(placeholder="PUBLIC USERNAME (NEW ACCOUNTS)", id="social-username")
                yield Input(placeholder="DISPLAY NAME (OPTIONAL)", id="social-display-name")
                with Horizontal(classes="social-button-row"):
                    yield Button("SIGN IN", id="social-sign-in", classes="social-action")
                    yield Button("CREATE", id="social-register", classes="social-action")
                    yield Button("FRIEND ZIP", id="social-friend-package", classes="social-action")
                    yield Button("SERVER", id="social-change-server", classes="social-muted-action")
            yield Static(
                "Your password is handled by Supabase Auth and is never stored in the local THRIVEBERG database.\n\n"
                "The public username is used for search, friend requests and conversations.",
                id="social-auth-note",
            )
        with Horizontal(id="social-dashboard"):
            with Vertical(id="social-directory"):
                yield Static("PEOPLE", classes="social-section-title")
                yield Input(placeholder="SEARCH USERNAME OR NAME", id="social-search")
                with Horizontal(classes="social-button-row"):
                    yield Button("SEARCH", id="social-search-button", classes="social-action")
                    yield Button("ADD", id="social-add", classes="social-action")
                yield OptionList(id="social-search-results")
                yield Static("FRIENDS / REQUESTS", classes="social-section-title")
                with Horizontal(classes="social-button-row"):
                    yield Button("ACCEPT", id="social-accept", classes="social-action")
                    yield Button("REJECT", id="social-reject", classes="social-action")
                    yield Button("REFRESH", id="social-refresh", classes="social-action")
                yield OptionList(id="social-connections")
                yield Button("SIGN OUT", id="social-sign-out", classes="social-muted-action")
            with Vertical(id="social-conversation"):
                yield Static("CHAT | SELECT A FRIEND", id="social-chat-header")
                with VerticalScroll(id="social-chat-scroll"):
                    yield Static("Select a friend to open the conversation.", id="social-chat")
                yield Static("NO ATTACHMENT", id="social-share-preview")
                yield Input(placeholder="WRITE A MESSAGE", id="social-message")
                with Horizontal(classes="social-button-row"):
                    yield Button("SEND", id="social-send", classes="social-action")
                    yield Button("LINK THRIVEBERG", id="social-share", classes="social-action")

    def on_mount(self) -> None:
        self.query_one("#social-dashboard").display = False
        if not self.service.configured:
            self.query_one("#social-auth").display = False
            self.query_one("#social-setup").display = True
            self._set_status("SOCIAL | SERVER REQUIRED", error=True)
        elif self.service.signed_in:
            self.query_one("#social-setup").display = False
            self.call_after_refresh(self._show_signed_in)
        else:
            self.query_one("#social-setup").display = False
            self._set_status("SIGN IN OR CREATE AN ACCOUNT")
        self.set_interval(4.0, self._poll_conversation)

    def set_share_context(self, command: str) -> None:
        self.share_command = " ".join(command.strip().upper().split())[:96]
        if self.is_mounted:
            label = f"READY TO LINK  {self.share_command}" if self.share_command else "NO ATTACHMENT"
            self.query_one("#social-share-preview", Static).update(label)

    async def activate(self) -> None:
        if self.service.signed_in:
            await self._show_signed_in()
        elif self.service.configured:
            self.query_one("#social-email", Input).focus()
        else:
            self.query_one("#social-server-url", Input).focus()

    @on(Button.Pressed)
    async def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        handlers = {
            "social-connect-server": self._configure_server,
            "social-change-server": self._show_server_setup,
            "social-friend-package": self._build_friend_package,
            "social-sign-in": self._sign_in,
            "social-register": self._register,
            "social-search-button": self._search,
            "social-add": self._add_selected,
            "social-accept": self._accept_selected,
            "social-reject": self._reject_selected,
            "social-refresh": self._refresh_connections,
            "social-send": self._send_message,
            "social-share": self._share_context,
            "social-sign-out": self._sign_out,
        }
        handler = handlers.get(button_id)
        if handler is not None:
            event.stop()
            await handler()

    async def _configure_server(self) -> None:
        url = self.query_one("#social-server-url", Input).value
        key = self.query_one("#social-server-key", Input).value
        self._set_status("CONNECTING TO SOCIAL SERVER")
        try:
            await self.service.configure(url, key)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self.query_one("#social-server-key", Input).value = ""
        self.query_one("#social-setup").display = False
        self.query_one("#social-auth").display = True
        self._set_status("SERVER CONNECTED | SIGN IN OR CREATE AN ACCOUNT")
        self.query_one("#social-email", Input).focus()

    async def _show_server_setup(self) -> None:
        provider = self.service.provider
        if provider is not None:
            self.query_one("#social-server-url", Input).value = provider.url
        self.query_one("#social-auth").display = False
        self.query_one("#social-setup").display = True
        self._set_status("SOCIAL | EDIT SERVER")
        self.query_one("#social-server-url", Input).focus()

    async def _build_friend_package(self) -> None:
        self._set_status("BUILDING FRIEND PACKAGE")
        try:
            path = await asyncio.to_thread(self.service.build_friend_package)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f"FRIEND PACKAGE READY | {path}")

    @on(Input.Submitted, "#social-search")
    async def search_submitted(self, _event: Input.Submitted) -> None:
        await self._search()

    @on(Input.Submitted, "#social-server-key")
    async def server_key_submitted(self, _event: Input.Submitted) -> None:
        await self._configure_server()

    @on(Input.Submitted, "#social-message")
    async def message_submitted(self, _event: Input.Submitted) -> None:
        await self._send_message()

    @on(OptionList.OptionSelected, "#social-search-results")
    def search_result_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.search_results):
            self.selected_user = self.search_results[event.option_index]
            self._update_selected_user()

    @on(OptionList.OptionSelected, "#social-connections")
    async def connection_selected(self, event: OptionList.OptionSelected) -> None:
        if not 0 <= event.option_index < len(self.connections):
            return
        connection = self.connections[event.option_index]
        self.selected_user = connection.user
        self._update_selected_user()
        if connection.friendship == FriendshipStatus.FRIENDS:
            await self._load_conversation()

    async def _sign_in(self) -> None:
        email = self.query_one("#social-email", Input).value
        password = self.query_one("#social-password", Input).value
        await self._run_auth(self.service.sign_in(email, password), "SIGNING IN")

    async def _register(self) -> None:
        email = self.query_one("#social-email", Input).value
        password = self.query_one("#social-password", Input).value
        username = self.query_one("#social-username", Input).value
        display_name = self.query_one("#social-display-name", Input).value
        self._set_status("CREATING ACCOUNT")
        try:
            session, message = await self.service.register(email, password, username, display_name)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self.query_one("#social-password", Input).value = ""
        self._set_status(message)
        if session is not None:
            await self._show_signed_in()

    async def _run_auth(self, operation, progress: str) -> None:
        self._set_status(progress)
        try:
            await operation
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self.query_one("#social-password", Input).value = ""
        await self._show_signed_in()

    async def _show_signed_in(self) -> None:
        session = self.service.session
        if session is None:
            return
        self.query_one("#social-auth").display = False
        self.query_one("#social-setup").display = False
        self.query_one("#social-dashboard").display = True
        self._set_status(
            f"CONNECTED | @{session.username.upper()} | {session.display_name.upper()} | PRIVATE MESSAGING"
        )
        self.query_one("#social-search", Input).focus()
        await self._refresh_connections()

    async def _sign_out(self) -> None:
        try:
            await self.service.sign_out()
        except Exception as exc:
            self._set_status(str(exc), error=True)
        self.selected_user = None
        self.search_results = []
        self.connections = []
        self.query_one("#social-dashboard").display = False
        self.query_one("#social-setup").display = False
        self.query_one("#social-auth").display = True
        self._set_status("SIGN IN OR CREATE AN ACCOUNT")
        self.query_one("#social-email", Input).focus()

    async def _search(self) -> None:
        query = self.query_one("#social-search", Input).value.strip()
        if len(query) < 2:
            self._set_status("Enter at least two characters", error=True)
            return
        self._set_status(f"SEARCHING  {query.upper()}")
        try:
            self.search_results = await self.service.search_users(query)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        menu = self.query_one("#social-search-results", OptionList)
        menu.clear_options()
        for index, user in enumerate(self.search_results):
            prompt = Text()
            prompt.append(f"@{user.username:<24}", style="bold cyan")
            prompt.append(f"{user.display_name:<28}", style="white")
            prompt.append(_relationship_label(user.friendship), style="yellow")
            menu.add_option(Option(prompt, id=f"social-user-{index}"))
        self._set_status(f"{len(self.search_results)} USERS FOUND")

    async def _refresh_connections(self) -> None:
        try:
            self.connections = await self.service.connections()
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        menu = self.query_one("#social-connections", OptionList)
        menu.clear_options()
        for index, connection in enumerate(self.connections):
            prompt = Text()
            prompt.append(f"@{connection.user.username:<22}", style="bold cyan")
            prompt.append(_relationship_label(connection.friendship), style="yellow")
            menu.add_option(Option(prompt, id=f"social-connection-{index}"))
        session = self.service.session
        if session is not None:
            self._set_status(f"CONNECTED AS @{session.username.upper()} | {len(self.connections)} CONNECTIONS")

    async def _add_selected(self) -> None:
        user = self.selected_user
        if user is None:
            self._set_status("Select a user first", error=True)
            return
        if user.friendship == FriendshipStatus.INCOMING:
            await self._respond(user.request_id, True)
            return
        if user.friendship != FriendshipStatus.NONE:
            self._set_status(_relationship_label(user.friendship))
            return
        try:
            await self.service.send_friend_request(user)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f"FRIEND REQUEST SENT TO @{user.username.upper()}")
        await self._refresh_connections()

    async def _accept_selected(self) -> None:
        user = self.selected_user
        if user is None or user.friendship != FriendshipStatus.INCOMING:
            self._set_status("Select an incoming request", error=True)
            return
        await self._respond(user.request_id, True)

    async def _reject_selected(self) -> None:
        user = self.selected_user
        if user is None or user.friendship != FriendshipStatus.INCOMING:
            self._set_status("Select an incoming request", error=True)
            return
        await self._respond(user.request_id, False)

    async def _respond(self, request_id: str, accept: bool) -> None:
        try:
            await self.service.respond_to_request(request_id, accept)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status("FRIEND REQUEST ACCEPTED" if accept else "FRIEND REQUEST REJECTED")
        await self._refresh_connections()

    async def _send_message(self) -> None:
        user = self.selected_user
        if user is None or user.friendship != FriendshipStatus.FRIENDS:
            self._set_status("Select a friend before sending a message", error=True)
            return
        message_input = self.query_one("#social-message", Input)
        try:
            await self.service.send_message(user, message_input.value)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        message_input.value = ""
        await self._load_conversation()

    async def _share_context(self) -> None:
        user = self.selected_user
        if user is None or user.friendship != FriendshipStatus.FRIENDS:
            self._set_status("Select a friend before linking a THRIVEBERG screen", error=True)
            return
        if not self.share_command:
            self._set_status("Open an instrument, chart or news screen before linking it", error=True)
            return
        body = self.query_one("#social-message", Input).value
        try:
            await self.service.send_message(user, body, self.share_command)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        self.query_one("#social-message", Input).value = ""
        await self._load_conversation()

    async def _load_conversation(self) -> None:
        user = self.selected_user
        session = self.service.session
        if user is None or session is None or user.friendship != FriendshipStatus.FRIENDS:
            return
        try:
            messages = await self.service.messages(user)
        except Exception as exc:
            self._set_status(str(exc), error=True)
            return
        transcript = Text()
        for message in messages:
            mine = message.is_mine(session)
            author = "YOU" if mine else f"@{user.username.upper()}"
            transcript.append(f"{message.created_at:%d %b %H:%M}  {author}\n", style="bold cyan" if mine else "bold yellow")
            if message.body:
                transcript.append(message.body, style="white")
                transcript.append("\n")
            if message.shared_command:
                command_style = f"app.run_command({message.shared_command!r})"
                transcript.append(
                    f" OPEN  {message.shared_command} \n",
                    style=Style(
                        color="cyan",
                        bold=True,
                        underline=False,
                        meta={"@click": command_style},
                    ),
                )
            transcript.append("\n")
        if not messages:
            transcript.append("No messages yet. Start the conversation.", style="dim")
        self.query_one("#social-chat-header", Static).update(
            f"CHAT | @{user.username.upper()} | {user.display_name.upper()}"
        )
        self.query_one("#social-chat", Static).update(transcript)
        self.call_after_refresh(self.query_one("#social-chat-scroll", VerticalScroll).scroll_end, animate=False)

    async def _poll_conversation(self) -> None:
        if not self.display or not self.service.signed_in or self.selected_user is None:
            return
        if self.selected_user.friendship == FriendshipStatus.FRIENDS:
            await self._load_conversation()

    def _update_selected_user(self) -> None:
        user = self.selected_user
        if user is None:
            return
        self._set_status(
            f"SELECTED @{user.username.upper()} | {user.display_name} | {_relationship_label(user.friendship)}"
        )

    def _set_status(self, message: str, error: bool = False) -> None:
        status = self.query_one("#social-status", Static)
        status.update(message)
        status.set_class(error, "error")


def _relationship_label(status: FriendshipStatus) -> str:
    return {
        FriendshipStatus.NONE: "ADD AVAILABLE",
        FriendshipStatus.OUTGOING: "REQUEST SENT",
        FriendshipStatus.INCOMING: "REQUEST RECEIVED",
        FriendshipStatus.FRIENDS: "FRIEND",
    }[status]
