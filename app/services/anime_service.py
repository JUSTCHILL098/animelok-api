"""Service layer for route handlers."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from app.services.anilist import AniListClient, AniListMappingStore, normalize_detail, title_candidates
from app.scrapers.animelok import AnimelokScraper
from app.utils.exceptions import NotFoundError


class AnimeService:
    """AniList-first service facade around the provider scraper."""

    def __init__(
        self,
        scraper: AnimelokScraper | None = None,
        anilist: AniListClient | None = None,
        mappings: AniListMappingStore | None = None,
    ) -> None:
        self.scraper = scraper or AnimelokScraper()
        self.anilist = anilist or AniListClient()
        self.mappings = mappings or AniListMappingStore()

    async def home(self) -> dict:
        trending = await self.anilist.popular(["TRENDING_DESC"], per_page=15)
        popular = await self.anilist.popular(["POPULARITY_DESC"], per_page=20)
        airing = await self.anilist.popular(["SCORE_DESC", "POPULARITY_DESC"], per_page=15)
        return {
            "spotlight_anime": trending[:5],
            "trending_anime": trending[:10],
            "latest_episodes": await self.anilist.popular(["UPDATED_AT_DESC"], per_page=20),
            "top_airing": airing,
            "most_popular": popular,
            "genres": [
                "Action",
                "Adventure",
                "Comedy",
                "Drama",
                "Fantasy",
                "Horror",
                "Mystery",
                "Romance",
                "Sci-Fi",
                "Slice of Life",
                "Sports",
                "Supernatural",
            ],
        }

    async def top_search(self) -> list[dict[str, str]]:
        items = await self.anilist.popular(["TRENDING_DESC"], per_page=10)
        return [{"title": item["title"], "link": f"/info/{item['anime_id']}"} for item in items]

    async def category(self, category: str, page: int = 1) -> dict:
        if category.startswith("genre/"):
            return await self.anilist.by_genre(category.split("/", 1)[1].replace("-", " "), page=page)
        return {"totalPages": 1, "data": await self.anilist.popular(["POPULARITY_DESC"], page=page, per_page=20)}

    async def search(self, query: str) -> list[dict]:
        return await self.anilist.search(query)

    async def search_suggest(self, query: str) -> list[dict]:
        return (await self.anilist.search(query, per_page=10))[:10]

    async def info(self, anime_id: str) -> dict:
        anilist_id = await self._anilist_id_for(anime_id)
        media = await self.anilist.media(anilist_id)
        provider_detail = await self._provider_detail_for(anilist_id, media, required=False)
        return normalize_detail(media, provider_detail)

    async def episodes(self, anime_id: str) -> list[dict]:
        provider_id = await self._provider_id_for(anime_id)
        episodes = await self.scraper.episodes(provider_id)
        public_id = str(await self._anilist_id_for(anime_id))
        return [
            {
                **episode,
                "episode_id": self.scraper.make_episode_id(public_id, int(episode["number"])),
            }
            for episode in episodes
        ]

    async def servers(self, episode_id: str) -> list[dict[str, str]]:
        provider_episode_id = await self._provider_episode_id(episode_id)
        return await self.scraper.servers(provider_episode_id)

    async def stream(self, episode_id: str) -> dict:
        provider_episode_id = await self._provider_episode_id(episode_id)
        return await self.scraper.stream(provider_episode_id)

    def episode_id_from_query(self, raw_id: str, ep: int | None = None) -> str:
        parsed = urlparse(raw_id)
        anime_id = (parsed.path or raw_id).strip("/")
        query = parse_qs(parsed.query)
        episode_number = ep or int(query.get("ep", ["1"])[0])
        return self.scraper.make_episode_id(anime_id, episode_number)

    async def _provider_episode_id(self, episode_id: str) -> str:
        anime_id, episode_number = self.scraper.split_episode_id(episode_id)
        provider_id = await self._provider_id_for(anime_id)
        return self.scraper.make_episode_id(provider_id, episode_number)

    async def _provider_id_for(self, anime_id: str) -> str:
        anilist_id = await self._anilist_id_for(anime_id)
        media = await self.anilist.media(anilist_id)
        provider_detail = await self._provider_detail_for(anilist_id, media, required=True)
        provider_id = str(provider_detail.get("anime_id") or "")
        if not provider_id:
            raise NotFoundError(f"Provider mapping missing for AniList ID {anilist_id}")
        return provider_id

    async def _anilist_id_for(self, anime_id: str) -> int:
        if anime_id.isdigit():
            return int(anime_id)
        detail = await self.scraper.info(anime_id)
        anilist_id = detail.get("anilist_id")
        if not anilist_id:
            raise NotFoundError(f"Anime not found: {anime_id}")
        await self.mappings.set(int(anilist_id), str(detail.get("anime_id") or anime_id))
        return int(anilist_id)

    async def _provider_detail_for(self, anilist_id: int, media: dict[str, Any], *, required: bool) -> dict[str, Any] | None:
        mapped = await self.mappings.get(anilist_id)
        if mapped:
            try:
                detail = await self.scraper.info(mapped)
                if int(detail.get("anilist_id") or 0) == anilist_id:
                    return detail
            except Exception:
                pass

        for title in title_candidates(media):
            for result in await self.scraper.search(title):
                provider_id = str(result.get("anime_id") or "")
                if not provider_id:
                    continue
                try:
                    detail = await self.scraper.info(provider_id)
                except Exception:
                    continue
                if int(detail.get("anilist_id") or 0) == anilist_id:
                    await self.mappings.set(anilist_id, provider_id)
                    return detail

        if required:
            raise NotFoundError(f"Could not map AniList ID {anilist_id} to a provider anime")
        return None


anime_service = AnimeService()
