from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ajax_terminal.models.social import ChatMessage, SocialSession, SocialUser
from ajax_terminal.providers.base import ProviderError
from ajax_terminal.utils.url_security import require_https_url


class SocialProviderError(ProviderError):
    pass


class SupabaseSocialProvider:
    name = "Supabase"

    def __init__(self, url: str, anon_key: str, timeout: int = 12) -> None:
        self.url = require_https_url(url).rstrip("/")
        self.anon_key = anon_key.strip()
        self.timeout = timeout

    async def health_check(self) -> None:
        payload = await self._request("GET", "/auth/v1/settings")
        if not isinstance(payload, dict):
            raise SocialProviderError("The social server returned an unexpected response")

    async def sign_up(
        self,
        email: str,
        password: str,
        username: str,
        display_name: str,
    ) -> SocialSession | None:
        payload = await self._request(
            "POST",
            "/auth/v1/signup",
            body={
                "email": email,
                "password": password,
                "data": {"username": username, "display_name": display_name or username},
            },
        )
        if not payload.get("access_token"):
            return None
        return _session_from_auth(payload, username, display_name)

    async def sign_in(self, email: str, password: str) -> SocialSession:
        payload = await self._request(
            "POST",
            "/auth/v1/token?grant_type=password",
            body={"email": email, "password": password},
        )
        session = _session_from_auth(payload)
        profile = await self.profile(session)
        if profile is not None:
            session = SocialSession(
                user_id=session.user_id,
                email=session.email,
                username=profile.username,
                display_name=profile.display_name,
                access_token=session.access_token,
                refresh_token=session.refresh_token,
            )
        return session

    async def sign_out(self, session: SocialSession) -> None:
        await self._request("POST", "/auth/v1/logout", session=session, body={})

    async def profile(self, session: SocialSession) -> SocialUser | None:
        rows = await self._rest_get(
            "profiles",
            session,
            {"select": "id,username,display_name,status", "id": f"eq.{session.user_id}", "limit": "1"},
        )
        return _social_user(rows[0]) if rows else None

    async def search_users(
        self,
        session: SocialSession,
        query: str,
        limit: int = 20,
    ) -> list[SocialUser]:
        clean = query.strip().replace("*", "")
        if not clean:
            return []
        rows = await self._rest_get(
            "profiles",
            session,
            {
                "select": "id,username,display_name,status",
                "or": f"(username.ilike.*{clean}*,display_name.ilike.*{clean}*)",
                "id": f"neq.{session.user_id}",
                "order": "username.asc",
                "limit": str(min(max(limit, 1), 50)),
            },
        )
        return [_social_user(row) for row in rows]

    async def connection_rows(self, session: SocialSession) -> list[dict[str, Any]]:
        return await self._rest_get(
            "friend_requests",
            session,
            {
                "select": "id,sender_id,receiver_id,status,created_at",
                "or": f"(sender_id.eq.{session.user_id},receiver_id.eq.{session.user_id})",
                "status": "in.(pending,accepted)",
                "order": "created_at.desc",
            },
        )

    async def profiles_by_ids(
        self,
        session: SocialSession,
        user_ids: list[str],
    ) -> dict[str, SocialUser]:
        unique = list(dict.fromkeys(user_id for user_id in user_ids if user_id))
        if not unique:
            return {}
        rows = await self._rest_get(
            "profiles",
            session,
            {
                "select": "id,username,display_name,status",
                "id": f"in.({','.join(unique)})",
            },
        )
        users = [_social_user(row) for row in rows]
        return {user.user_id: user for user in users}

    async def send_friend_request(self, session: SocialSession, user_id: str) -> None:
        if user_id == session.user_id:
            raise SocialProviderError("You cannot add yourself")
        await self._request(
            "POST",
            "/rest/v1/friend_requests",
            session=session,
            body={"sender_id": session.user_id, "receiver_id": user_id, "status": "pending"},
            extra_headers={"Prefer": "return=minimal"},
        )

    async def update_friend_request(
        self,
        session: SocialSession,
        request_id: str,
        status: str,
    ) -> None:
        if status not in {"accepted", "rejected"}:
            raise ValueError("Invalid friend request status")
        query = urllib.parse.urlencode(
            {"id": f"eq.{request_id}", "receiver_id": f"eq.{session.user_id}", "status": "eq.pending"}
        )
        await self._request(
            "PATCH",
            f"/rest/v1/friend_requests?{query}",
            session=session,
            body={"status": status},
            extra_headers={"Prefer": "return=minimal"},
        )

    async def messages(
        self,
        session: SocialSession,
        other_user_id: str,
        limit: int = 200,
    ) -> list[ChatMessage]:
        conversation_filter = (
            f"(and(sender_id.eq.{session.user_id},recipient_id.eq.{other_user_id}),"
            f"and(sender_id.eq.{other_user_id},recipient_id.eq.{session.user_id}))"
        )
        rows = await self._rest_get(
            "messages",
            session,
            {
                "select": "id,sender_id,recipient_id,body,shared_command,created_at",
                "or": conversation_filter,
                "order": "created_at.asc",
                "limit": str(min(max(limit, 1), 500)),
            },
        )
        return [_chat_message(row) for row in rows]

    async def send_message(
        self,
        session: SocialSession,
        recipient_id: str,
        body: str,
        shared_command: str = "",
    ) -> None:
        await self._request(
            "POST",
            "/rest/v1/messages",
            session=session,
            body={
                "sender_id": session.user_id,
                "recipient_id": recipient_id,
                "body": body,
                "shared_command": shared_command or None,
            },
            extra_headers={"Prefer": "return=minimal"},
        )

    async def _rest_get(
        self,
        table: str,
        session: SocialSession,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(params, safe="().,*")
        payload = await self._request("GET", f"/rest/v1/{table}?{query}", session=session)
        if not isinstance(payload, list):
            raise SocialProviderError("Social API returned an unexpected response")
        return [row for row in payload if isinstance(row, dict)]

    async def _request(
        self,
        method: str,
        path: str,
        session: SocialSession | None = None,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        return await asyncio.to_thread(
            self._request_sync,
            method,
            path,
            session,
            body,
            extra_headers,
        )

    def _request_sync(
        self,
        method: str,
        path: str,
        session: SocialSession | None,
        body: dict[str, Any] | None,
        extra_headers: dict[str, str] | None,
    ) -> Any:
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {session.access_token if session else self.anon_key}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc.read())
            raise SocialProviderError(detail or f"Social API returned HTTP {exc.code}") from exc
        except Exception as exc:  # pragma: no cover - network dependent
            raise SocialProviderError(f"Could not reach the social service: {exc}") from exc
        if not payload:
            return {}
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SocialProviderError("Social API returned invalid JSON") from exc


def _session_from_auth(
    payload: dict[str, Any],
    username: str = "",
    display_name: str = "",
) -> SocialSession:
    user = payload.get("user") or {}
    metadata = user.get("user_metadata") or {}
    user_id = str(user.get("id", ""))
    access_token = str(payload.get("access_token", ""))
    if not user_id or not access_token:
        raise SocialProviderError("Authentication response did not contain a valid session")
    selected_username = str(metadata.get("username") or username or user.get("email", "user").split("@", 1)[0])
    selected_display = str(metadata.get("display_name") or display_name or selected_username)
    return SocialSession(
        user_id=user_id,
        email=str(user.get("email", "")),
        username=selected_username,
        display_name=selected_display,
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token", "")),
    )


def _social_user(row: dict[str, Any]) -> SocialUser:
    return SocialUser(
        user_id=str(row.get("id", "")),
        username=str(row.get("username", "")),
        display_name=str(row.get("display_name", "")),
        status=str(row.get("status", "")),
    )


def _chat_message(row: dict[str, Any]) -> ChatMessage:
    created_at = str(row.get("created_at", ""))
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        timestamp = datetime.now(timezone.utc)
    return ChatMessage(
        message_id=str(row.get("id", "")),
        sender_id=str(row.get("sender_id", "")),
        recipient_id=str(row.get("recipient_id", "")),
        body=str(row.get("body", "")),
        shared_command=str(row.get("shared_command") or ""),
        created_at=timestamp,
    )


def _error_detail(payload: bytes) -> str:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload.decode("utf-8", errors="replace")[:240]
    if not isinstance(data, dict):
        return str(data)[:240]
    return str(
        data.get("msg")
        or data.get("message")
        or data.get("error_description")
        or data.get("error")
        or ""
    )[:240]
