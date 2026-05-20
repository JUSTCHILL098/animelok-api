"""AniList metadata and provider mapping helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from app.cache.memory import cache
from app.utils.http import http_client

logger = logging.getLogger(__name__)

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
MAPPING_PATH = Path(__file__).resolve().parents[1] / "cache" / "anilist_mappings.json"
FALLBACK_MAPPING_PATH = Path(tempfile.gettempdir()) / "animelok_anilist_mappings.json"


class AniListClient:
    """Small AniList GraphQL client."""

    async def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        data = await http_client.post_json(
            ANILIST_GRAPHQL_URL,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"query": query, "variables": variables},
        )
        if not isinstance(data, dict) or data.get("errors"):
            raise ValueError(f"AniList request failed: {data.get('errors') if isinstance(data, dict) else data}")
        return data.get("data") or {}

    async def media(self, anilist_id: int) -> dict[str, Any]:
        key = f"anilist:media:{anilist_id}"

        async def factory() -> dict[str, Any]:
            data = await self.execute(MEDIA_QUERY, {"id": anilist_id})
            return data.get("Media") or {}

        return await cache.get_or_set(key, factory)

    async def search(self, query: str, page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        data = await self.execute(SEARCH_QUERY, {"search": query, "page": page, "perPage": per_page})
        media = ((data.get("Page") or {}).get("media") or []) if isinstance(data, dict) else []
        return [normalize_card(item) for item in media if isinstance(item, dict)]

    async def popular(self, sort: list[str], page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        data = await self.execute(POPULAR_QUERY, {"sort": sort, "page": page, "perPage": per_page})
        media = ((data.get("Page") or {}).get("media") or []) if isinstance(data, dict) else []
        return [normalize_card(item) for item in media if isinstance(item, dict)]

    async def by_genre(self, genre: str, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        data = await self.execute(GENRE_QUERY, {"genre": genre, "page": page, "perPage": per_page})
        page_data = data.get("Page") or {}
        media = page_data.get("media") or []
        page_info = page_data.get("pageInfo") or {}
        return {
            "totalPages": page_info.get("lastPage") or 1,
            "data": [normalize_card(item) for item in media if isinstance(item, dict)],
        }


class AniListMappingStore:
    """Persistent AniList ID to provider slug mapping store."""

    def __init__(self, path: Path = MAPPING_PATH) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def get(self, anilist_id: int) -> str | None:
        async with self._lock:
            mappings = self._read()
            return mappings.get(str(anilist_id))

    async def set(self, anilist_id: int, provider_id: str) -> None:
        async with self._lock:
            mappings = self._read()
            mappings[str(anilist_id)] = provider_id
            self._write(mappings)

    def _read(self) -> dict[str, str]:
        data: dict[str, Any] = {}
        for path in [self.path, FALLBACK_MAPPING_PATH]:
            if not path.exists():
                continue
            try:
                data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return {str(key): str(value) for key, value in data.items() if value}

    def _write(self, mappings: dict[str, str]) -> None:
        payload = json.dumps(mappings, indent=2, sort_keys=True)
        for path in [self.path, FALLBACK_MAPPING_PATH]:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")
                return
            except OSError:
                continue
        logger.info("unable to persist AniList mappings")


def normalize_card(media: dict[str, Any]) -> dict[str, Any]:
    title = media.get("title") or {}
    cover = media.get("coverImage") or {}
    return {
        "anime_id": str(media.get("id")),
        "anilist_id": media.get("id"),
        "title": title.get("english") or title.get("romaji") or title.get("native") or str(media.get("id")),
        "japanese_title": title.get("native"),
        "poster": cover.get("extraLarge") or cover.get("large") or cover.get("medium"),
        "episodes": media.get("episodes"),
        "type": media.get("format"),
        "year": (media.get("startDate") or {}).get("year"),
    }


def normalize_detail(media: dict[str, Any], provider_detail: dict[str, Any] | None = None) -> dict[str, Any]:
    card = normalize_card(media)
    title = media.get("title") or {}
    cover = media.get("coverImage") or {}
    banner = media.get("bannerImage")
    studios = [edge.get("node", {}).get("name") for edge in ((media.get("studios") or {}).get("edges") or []) if edge.get("node")]
    characters = []
    for edge in ((media.get("characters") or {}).get("edges") or []):
        node = edge.get("node") or {}
        characters.append(
            {
                "id": node.get("id"),
                "name": (node.get("name") or {}).get("full"),
                "image": (node.get("image") or {}).get("large"),
                "role": edge.get("role"),
            }
        )
    relations = [normalize_card(edge["node"]) for edge in ((media.get("relations") or {}).get("edges") or []) if isinstance(edge.get("node"), dict)]
    recommendations = [
        normalize_card((item.get("mediaRecommendation") or {}))
        for item in ((media.get("recommendations") or {}).get("nodes") or [])
        if isinstance(item.get("mediaRecommendation"), dict)
    ]
    detail = {
        **card,
        "title": title.get("english") or title.get("romaji") or title.get("native") or card["title"],
        "romaji_title": title.get("romaji"),
        "english_title": title.get("english"),
        "native_title": title.get("native"),
        "banner": banner,
        "poster": cover.get("extraLarge") or cover.get("large") or card.get("poster"),
        "synopsis": media.get("description"),
        "description": media.get("description"),
        "genres": media.get("genres") or [],
        "studios": studios,
        "rating": media.get("averageScore"),
        "popularity": media.get("popularity"),
        "status": media.get("status"),
        "season": media.get("season"),
        "season_year": media.get("seasonYear"),
        "airing_info": media.get("nextAiringEpisode"),
        "nextEpisode": media.get("nextAiringEpisode"),
        "characters": characters,
        "related_anime": relations,
        "recommended_anime": recommendations,
        "relations": relations,
        "recommendations": recommendations,
        "mal_id": media.get("idMal"),
        "source": media.get("source"),
    }
    if provider_detail:
        detail["available_languages"] = provider_detail.get("available_languages") or []
        detail["episode_counts"] = provider_detail.get("episode_counts") or {}
        detail["total_episodes"] = provider_detail.get("total_episodes") or detail.get("episodes")
    return detail


def title_candidates(media: dict[str, Any]) -> list[str]:
    title = media.get("title") or {}
    values = [title.get("english"), title.get("romaji"), title.get("native"), *(media.get("synonyms") or [])]
    seen: set[str] = set()
    candidates: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        candidates.append(value)
    return candidates


MEDIA_FIELDS = """
id idMal format status season seasonYear episodes duration averageScore popularity genres synonyms description(asHtml: false)
source bannerImage
title { romaji english native }
coverImage { extraLarge large medium }
startDate { year month day }
nextAiringEpisode { airingAt episode timeUntilAiring }
studios(isMain: true) { edges { node { id name } } }
characters(sort: ROLE, perPage: 12) { edges { role node { id name { full } image { large } } } }
relations { edges { relationType node { id idMal format episodes startDate { year } title { romaji english native } coverImage { extraLarge large medium } } } }
recommendations(sort: RATING_DESC, perPage: 12) { nodes { mediaRecommendation { id idMal format episodes startDate { year } title { romaji english native } coverImage { extraLarge large medium } } } }
"""

MEDIA_QUERY = f"query ($id: Int!) {{ Media(id: $id, type: ANIME) {{ {MEDIA_FIELDS} }} }}"
SEARCH_QUERY = f"query ($search: String!, $page: Int!, $perPage: Int!) {{ Page(page: $page, perPage: $perPage) {{ media(search: $search, type: ANIME) {{ {MEDIA_FIELDS} }} }} }}"
POPULAR_QUERY = f"query ($sort: [MediaSort], $page: Int!, $perPage: Int!) {{ Page(page: $page, perPage: $perPage) {{ media(type: ANIME, sort: $sort) {{ {MEDIA_FIELDS} }} }} }}"
GENRE_QUERY = f"query ($genre: String!, $page: Int!, $perPage: Int!) {{ Page(page: $page, perPage: $perPage) {{ pageInfo {{ lastPage }} media(type: ANIME, genre: $genre, sort: POPULARITY_DESC) {{ {MEDIA_FIELDS} }} }} }}"
