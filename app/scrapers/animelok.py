"""Animelok scraper implementation."""

from __future__ import annotations

import base64
import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

from app.cache.memory import cache
from app.config import settings
from app.parsers import parse_cards, parse_detail_from_watch, parse_genres, section_cards
from app.utils.exceptions import NotFoundError, StreamExtractionError
from app.utils.http import http_client
from app.utils.m3u8 import parse_master_playlist, parse_qualities

logger = logging.getLogger(__name__)


class AnimelokScraper:
    """Async scraper for Animelok and similar Next.js anime sites."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.normalized_base_url).rstrip("/")

    def url(self, path: str) -> str:
        """Build an absolute URL for the configured site."""

        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    async def home(self) -> dict[str, Any]:
        """Scrape the home page sections."""

        async def factory() -> dict[str, Any]:
            html = await http_client.get_text(self.url("/home"))
            cards = parse_cards(html)
            return {
                "spotlight_anime": section_cards(html, "spotlight") or cards[:5],
                "trending_anime": section_cards(html, "trending") or cards[:10],
                "latest_episodes": section_cards(html, "latest") or cards[:20],
                "top_airing": section_cards(html, "top airing") or cards[20:35],
                "most_popular": section_cards(html, "most popular") or cards[35:50],
                "genres": parse_genres(html),
            }

        return await cache.get_or_set("home", factory)

    async def top_search(self) -> list[dict[str, str]]:
        """Return top search links from the landing page."""

        async def factory() -> list[dict[str, str]]:
            html = await http_client.get_text(self.url("/"))
            links: list[dict[str, str]] = []
            for title in re.findall(r'href="/search\?keyword=([^"]+)">([^<]+)</a>', html):
                links.append({"title": re.sub(r"\s+", " ", title[1]).strip(), "link": f"/search?keyword={title[0]}"})
            return links

        return await cache.get_or_set("top-search", factory)

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Search anime by keyword."""

        key = f"search:{query.lower().strip()}"

        async def factory() -> list[dict[str, Any]]:
            html = await http_client.get_text(self.url(f"/search?keyword={quote(query)}"))
            return parse_cards(html)

        return await cache.get_or_set(key, factory)

    async def category(self, category: str, page: int = 1) -> dict[str, Any]:
        """Scrape a category/listing page."""

        normalized = category.strip("/")
        key = f"category:{normalized}:{page}"

        async def factory() -> dict[str, Any]:
            separator = "&" if "?" in normalized else "?"
            html = await http_client.get_text(self.url(f"/{normalized}{separator}page={page}"))
            return {"totalPages": self._parse_total_pages(html), "data": parse_cards(html)}

        return await cache.get_or_set(key, factory)

    async def search_suggest(self, query: str) -> list[dict[str, Any]]:
        """Return lightweight search suggestions."""

        return (await self.search(query))[:10]

    async def info(self, anime_id: str) -> dict[str, Any]:
        """Return anime details using the watch page's embedded data."""

        key = f"info:{anime_id}"

        async def factory() -> dict[str, Any]:
            html = await http_client.get_text(self.url(f"/watch/{anime_id}"))
            detail = parse_detail_from_watch(anime_id, html)
            if not detail.get("anilist_id"):
                raise NotFoundError(f"Anime not found: {anime_id}")
            detail["recommended_anime"] = await self._resolve_related(detail.get("source_id"), "recommendations")
            detail["related_anime"] = await self._resolve_related(detail.get("source_id"), "relations")
            return detail

        return await cache.get_or_set(key, factory)

    async def episodes(self, anime_id: str) -> list[dict[str, Any]]:
        """Return episode IDs and numbers for an anime."""

        detail = await self.info(anime_id)
        slug = str(detail.get("slug") or anime_id)
        total = max(int(detail.get("total_episodes") or 1), 1)
        pages = max((total + 99) // 100, 1)
        episode_map: dict[int, dict[str, Any]] = {}
        for page in range(pages):
            try:
                data = await http_client.get_json(
                    self.url(f"/api/anime/{slug}/episodes-range"),
                    params={"page": page, "lang": "ALL", "pageSize": 100},
                    headers={"Referer": self.url(f"/watch/{slug}")},
                )
            except Exception:
                continue
            for episode in data.get("episodes", []) if isinstance(data, dict) else []:
                number = int(episode.get("number") or 0)
                if number <= 0:
                    continue
                episode_map[number] = {
                    "episode_id": self.make_episode_id(slug, number),
                    "number": number,
                    "title": episode.get("name") or f"Episode {number}",
                    "image": episode.get("img"),
                    "is_filler": bool(episode.get("isFiller")),
                    "description": episode.get("description"),
                }
        if episode_map:
            return [episode_map[number] for number in sorted(episode_map)]
        return [{"episode_id": self.make_episode_id(slug, number), "number": number, "title": f"Episode {number}"} for number in range(1, total + 1)]

    @staticmethod
    def make_episode_id(anime_id: str, episode_number: int) -> str:
        """Encode an anime ID and episode number into one path-safe ID."""

        return f"{anime_id}__ep__{episode_number}"

    @staticmethod
    def split_episode_id(episode_id: str) -> tuple[str, int]:
        """Decode an episode ID from this API or common watch-style IDs."""

        if "__ep__" in episode_id:
            anime_id, number = episode_id.rsplit("__ep__", 1)
            return anime_id, int(number)
        ep_match = re.search(r"(?:^|[-_:])ep(?:isode)?[-_:]?(\d+)$", episode_id, re.I)
        if ep_match:
            anime_id = episode_id[: ep_match.start()].rstrip("-_:")
            return anime_id, int(ep_match.group(1))
        raise NotFoundError("episode_id must look like '<anime_id>__ep__<number>'")

    async def servers(self, episode_id: str) -> list[dict[str, Any]]:
        """Return every server exposed by Animelok for an episode."""

        anime_id, episode_number = self.split_episode_id(episode_id)
        episode_data = await self._fetch_episode_data(anime_id, episode_number)
        episode = episode_data.get("episode") or {}
        return self._normalize_servers(episode.get("servers") or [])

    async def stream(self, episode_id: str, server: str = "multi") -> dict[str, Any]:
        """Resolve a stream for the requested Animelok server."""

        anime_id, episode_number = self.split_episode_id(episode_id)
        episode_data = await self._fetch_episode_data(anime_id, episode_number)
        episode = episode_data.get("episode") or {}
        selected_server = self._find_server(episode, server)
        server_url = selected_server.get("url")
        if not server_url:
            raise StreamExtractionError(f"{selected_server.get('name') or server} server did not include an embed URL")

        watch_url = self.url(f"/watch/{anime_id}?ep={episode_number}")
        server_name = str(selected_server.get("name") or selected_server.get("tip") or server)
        if self._is_multi_server(selected_server):
            player = await self._fetch_multi_player(server_url, watch_url)
        else:
            player = await self._fetch_embed_player(server_url, watch_url)
        stream_url = player.get("videoSource") or player.get("securedLink")
        if not stream_url:
            stream_url = self._extract_m3u8_from_text(str(player))
        if not stream_url:
            raise StreamExtractionError(f"{server_name} server did not return an HLS source")
        playlist_headers = {
            "Referer": server_url,
            "Origin": self._origin(server_url),
            "User-Agent": http_client.default_headers()["User-Agent"],
        }
        playlist = await http_client.get_text(stream_url, headers=playlist_headers)
        parsed_playlist = parse_master_playlist(stream_url, playlist)
        subtitles = self._normalize_tracks(episode.get("subtitles") or [])
        intro = self._timestamp_pair(episode.get("introStart"), episode.get("introEnd"))
        outro = self._timestamp_pair(episode.get("outroStart"), episode.get("outroEnd"))
        return {
            "stream_url": stream_url,
            "subtitles": subtitles,
            "audio_tracks": parsed_playlist["audio_tracks"],
            "intro": intro,
            "outro": outro,
            "qualities": parsed_playlist["qualities"],
            "server": server_name,
            "type": self._server_type(selected_server),
            "headers": playlist_headers,
        }

    async def _fetch_episode_data(self, anime_id: str, episode_number: int) -> dict[str, Any]:
        """Fetch Animelok episode metadata and original server list."""

        detail = await self.info(anime_id)
        slug = str(detail.get("slug") or anime_id)
        data = await http_client.get_json(
            self.url(f"/api/anime/{slug}/episodes/{episode_number}"),
            headers={
                "Referer": self.url(f"/watch/{slug}?ep={episode_number}"),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )
        if not isinstance(data, dict) or not data.get("episode"):
            raise StreamExtractionError("Episode metadata was not returned")
        return data

    def _normalize_servers(self, servers: Any) -> list[dict[str, Any]]:
        """Normalize Animelok's raw server objects without hiding backups."""

        normalized: list[dict[str, Any]] = []
        for index, server in enumerate(servers if isinstance(servers, list) else [], start=1):
            if not isinstance(server, dict):
                continue
            name = str(server.get("name") or server.get("tip") or server.get("serverName") or f"server-{index}").strip()
            server_url = str(server.get("url") or server.get("link") or server.get("embed") or "").strip()
            normalized.append(
                {
                    "server": name.lower(),
                    "server_name": name,
                    "type": self._server_type(server),
                    "server_id": server.get("id") or server.get("server_id") or index,
                    "data_id": server.get("data_id") or server.get("dataId") or index,
                    "url": urljoin(self.base_url, server_url) if server_url else None,
                }
            )
        return normalized

    def _find_server(self, episode: dict[str, Any], selected: str = "multi") -> dict[str, Any]:
        """Find a server by name, tip, ID, or one-based position."""

        raw_servers = [server for server in episode.get("servers") or [] if isinstance(server, dict)]
        if not raw_servers:
            raise StreamExtractionError("No servers are available for this episode")

        wanted = str(selected or "multi").lower().strip()
        for index, server in enumerate(raw_servers, start=1):
            names = {
                str(server.get("name") or "").lower().strip(),
                str(server.get("tip") or "").lower().strip(),
                str(server.get("serverName") or "").lower().strip(),
            }
            ids = {
                str(server.get("id") or "").lower().strip(),
                str(server.get("server_id") or "").lower().strip(),
                str(server.get("data_id") or "").lower().strip(),
                str(index),
            }
            if wanted in names or wanted in ids:
                found = dict(server)
                server_url = str(found.get("url") or found.get("link") or found.get("embed") or "").strip()
                if server_url:
                    found["url"] = urljoin(self.base_url, server_url)
                return found

        available = ", ".join(item["server_name"] for item in self._normalize_servers(raw_servers))
        raise StreamExtractionError(f"Server '{selected}' is not available for this episode. Available servers: {available}")

    @staticmethod
    def _is_multi_server(server: dict[str, Any]) -> bool:
        """Return whether a raw server object points at Animelok's Multi player."""

        name = str(server.get("name") or "").lower()
        tip = str(server.get("tip") or "").lower()
        url = str(server.get("url") or "").lower()
        return name == "multi" or tip == "multi" or "as-cdn" in url

    @staticmethod
    def _server_type(server: dict[str, Any]) -> str:
        """Infer the playback language bucket for compatibility responses."""

        explicit = server.get("type") or server.get("category") or server.get("lang")
        value = str(explicit or server.get("name") or server.get("tip") or "").lower()
        if "dub" in value:
            return "dub"
        if "raw" in value:
            return "raw"
        return "sub"

    async def _fetch_multi_player(self, server_url: str, watch_url: str) -> dict[str, Any]:
        """Resolve an as-cdn Multi page to its signed HLS URL."""

        parsed = urlparse(server_url)
        token = parsed.path.rstrip("/").split("/")[-1]
        if not token:
            raise StreamExtractionError("Invalid Multi server URL")
        player_url = f"{parsed.scheme}://{parsed.netloc}/player/index.php?data={token}&do=getVideo"
        data = await http_client.post_json(
            player_url,
            headers={
                "Accept": "application/json,text/javascript,*/*;q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": f"{parsed.scheme}://{parsed.netloc}",
                "Referer": server_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            data={"hash": token, "r": watch_url},
        )
        if not isinstance(data, dict):
            raise StreamExtractionError("Invalid Multi player response")
        return data

    async def _fetch_embed_player(self, server_url: str, watch_url: str) -> dict[str, Any]:
        """Resolve a non-Multi embed page when it exposes an HLS URL directly."""

        html = await http_client.get_text(server_url, headers={"Referer": watch_url})
        stream_url = self._extract_m3u8_from_text(html)
        if not stream_url:
            decoded_candidates = [self._decode_base64(candidate) for candidate in re.findall(r"['\"]([A-Za-z0-9+/=]{40,})['\"]", html)]
            stream_url = next((self._extract_m3u8_from_text(item or "") for item in decoded_candidates if item), None)
        return {"videoSource": stream_url} if stream_url else {}

    @staticmethod
    def _normalize_tracks(tracks: Any) -> list[dict[str, Any]]:
        """Return subtitle tracks in a clean list."""

        if not tracks:
            return []
        normalized: list[dict[str, Any]] = []
        for track in tracks if isinstance(tracks, list) else []:
            if not isinstance(track, dict):
                continue
            url = track.get("file") or track.get("url") or track.get("src")
            if not url:
                continue
            normalized.append(
                {
                    "label": track.get("label") or track.get("name") or "Subtitle",
                    "kind": track.get("kind") or "subtitles",
                    "url": url,
                    "default": bool(track.get("default")),
                }
            )
        return normalized

    @staticmethod
    def _timestamp_pair(start: Any, end: Any) -> dict[str, Any]:
        """Return a timestamp object only when both values are present."""

        if start is None or end is None:
            return {}
        return {"start": start, "end": end}

    @staticmethod
    def _parse_chapters(chapters: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Extract intro and outro chapter timestamps."""

        intro: dict[str, Any] = {}
        outro: dict[str, Any] = {}
        for chapter in chapters:
            title = str(chapter.get("title", "")).lower()
            item = {"start": chapter.get("start"), "end": chapter.get("end")}
            if "intro" in title:
                intro = item
            elif "outro" in title or "ending" in title:
                outro = item
        return intro, outro

    async def _resolve_related(self, source_id: int | None, relation_type: str) -> list[dict[str, Any]]:
        """Resolve related/recommended anime IDs through the public site API."""

        if not source_id:
            return []
        try:
            data = await http_client.get_json(
                self.url("/api/anime/related"),
                params={"animeId": source_id, "type": relation_type, "take": 12, "v": 2},
            )
        except Exception as exc:
            logger.info("related lookup failed", extra={"source_id": source_id, "type": relation_type, "error": str(exc)})
            return []
        anime = data.get("anime") if isinstance(data, dict) else []
        return anime if isinstance(anime, list) else []

    @staticmethod
    def _parse_total_pages(page_html: str) -> int:
        """Best-effort pagination parser."""

        numbers = [int(item) for item in re.findall(r">\s*(\d{1,4})\s*</button>", page_html)]
        return max(numbers or [1])

    @staticmethod
    def _origin(url: str) -> str:
        """Return URL origin."""

        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def episode_id_from_query(raw_id: str, ep: int | None = None) -> str:
        """Normalize HiAnime-style id plus ep query into this API's episode_id."""

        parsed = urlparse(raw_id)
        anime_id = parsed.path or raw_id
        query = parse_qs(parsed.query)
        episode_number = ep or int(query.get("ep", ["1"])[0])
        return AnimelokScraper.make_episode_id(anime_id, episode_number)

    async def extract_from_embed_page(self, embed_url: str) -> dict[str, Any]:
        """Generic fallback extractor for Multi-like embed pages.

        This handles direct m3u8 URLs, JSON source arrays, simple base64 wrappers,
        and common packed JavaScript strings. It is intentionally only used for
        Multi/Vibe style pages and never enumerates backup servers.
        """

        html = await http_client.get_text(embed_url, headers={"Referer": self.base_url})
        stream_url = self._extract_m3u8_from_text(html)
        if not stream_url:
            decoded_candidates = [self._decode_base64(candidate) for candidate in re.findall(r"['\"]([A-Za-z0-9+/=]{40,})['\"]", html)]
            stream_url = next((self._extract_m3u8_from_text(item or "") for item in decoded_candidates if item), None)
        if not stream_url:
            raise StreamExtractionError("Unable to resolve m3u8 from multi embed")
        playlist = await http_client.get_text(stream_url, headers={"Referer": embed_url})
        return {
            "stream_url": stream_url,
            "subtitles": [],
            "audio_tracks": parse_master_playlist(stream_url, playlist)["audio_tracks"],
            "intro": {},
            "outro": {},
            "qualities": parse_qualities(stream_url, playlist),
        }

    @staticmethod
    def _extract_m3u8_from_text(value: str) -> str | None:
        """Find an m3u8 URL in text or escaped JavaScript."""

        unescaped = value.replace("\\/", "/").replace("\\u0026", "&")
        match = re.search(r"https?://[^'\"<>\s]+?\.m3u8[^'\"<>\s]*", unescaped)
        return match.group(0) if match else None

    @staticmethod
    def _decode_base64(value: str) -> str | None:
        """Decode a base64 string if possible."""

        try:
            padding = "=" * (-len(value) % 4)
            return base64.b64decode(value + padding).decode("utf-8", errors="ignore")
        except Exception:
            return None
