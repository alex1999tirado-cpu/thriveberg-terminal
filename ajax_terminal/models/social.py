from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FriendshipStatus(StrEnum):
    NONE = "NONE"
    OUTGOING = "OUTGOING"
    INCOMING = "INCOMING"
    FRIENDS = "FRIENDS"


@dataclass(frozen=True, slots=True)
class SocialSession:
    user_id: str
    email: str
    username: str
    display_name: str
    access_token: str
    refresh_token: str = ""


@dataclass(frozen=True, slots=True)
class SocialUser:
    user_id: str
    username: str
    display_name: str
    status: str = ""
    friendship: FriendshipStatus = FriendshipStatus.NONE
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class FriendConnection:
    request_id: str
    user: SocialUser
    friendship: FriendshipStatus
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChatMessage:
    message_id: str
    sender_id: str
    recipient_id: str
    body: str
    shared_command: str
    created_at: datetime

    def is_mine(self, session: SocialSession) -> bool:
        return self.sender_id == session.user_id
