"""Response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnimeCard(BaseModel):
    anime_id: str
    title: str
    japanese_title: str | None = None
    poster: str | None = None
    episodes: int | None = None
    type: str | None = None
    year: int | None = None


class Episode(BaseModel):
    episode_id: str
    number: int
    title: str | None = None


class Server(BaseModel):
    server: str = "multi"
    type: str = "sub"


class StreamResults(BaseModel):
    stream_url: str
    subtitles: list[dict[str, Any]] = Field(default_factory=list)
    audio_tracks: list[dict[str, Any]] = Field(default_factory=list)
    intro: dict[str, Any] = Field(default_factory=dict)
    outro: dict[str, Any] = Field(default_factory=dict)
    qualities: list[dict[str, Any]] = Field(default_factory=list)


class StreamResponse(BaseModel):
    success: bool = True
    results: StreamResults
