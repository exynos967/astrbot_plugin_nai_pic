"""Shared dataclasses for the AstrBot NAI picture plugin."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ArtistPreset:
    name: str
    prompt: str


@dataclass(slots=True)
class RecentImageRecord:
    message_id: str
    prompt: str
    created_at: float


@dataclass(slots=True)
class PromptBuildResult:
    prompt: str
    display_prompt: str
    is_selfie: bool = False


@dataclass(slots=True)
class SessionContext:
    platform: str
    chat_id: str
    user_id: str
    is_group: bool
    is_admin: bool

    @property
    def session_key(self) -> str:
        return f"{self.platform}:{self.chat_id}"

    @classmethod
    def from_event(cls, event: Any) -> "SessionContext":
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        return cls(
            platform=str(event.get_platform_name() or ""),
            chat_id=group_id or user_id,
            user_id=user_id,
            is_group=bool(group_id),
            is_admin=bool(getattr(event, "is_admin", lambda: False)()),
        )


@dataclass(slots=True)
class SessionRuntimeState:
    admin_mode: bool | None = None
    selected_model: str | None = None
    selected_artist_index: int | None = None
    selected_size: str | None = None
    recall_enabled: bool | None = None
    nsfw_filter_enabled: bool | None = None
    prompt_show_enabled: bool | None = None
    recent_images: deque[RecentImageRecord] = field(
        default_factory=lambda: deque(maxlen=20)
    )
