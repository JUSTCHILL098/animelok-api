"""Anime REST endpoints."""

from __future__ import annotations

from datetime import date
from random import choice

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import AnimeCard, Episode, Server, StreamResponse, StreamResults
from app.services.anime_service import anime_service

router = APIRouter(prefix="/api", tags=["anime"])


@router.get("/")
async def hianime_home() -> dict:
    """HiAnime-style home endpoint."""

    return {"success": True, "results": await anime_service.home()}


@router.get("/home")
async def home() -> dict:
    """Return home page anime sections."""

    return await anime_service.home()


@router.get("/top-search")
async def top_search() -> dict:
    """Return top search terms."""

    return {"success": True, "results": await anime_service.top_search()}


@router.get("/top-ten")
async def top_ten() -> dict:
    """Return a best-effort top-ten response."""

    home_data = await anime_service.home()
    trending = home_data.get("trending_anime", [])[:10]
    return {"success": True, "results": {"topTen": {"today": trending, "week": trending, "month": trending}}}


@router.get("/random")
async def random_anime() -> dict:
    """Return a random anime from home/searchable listings."""

    home_data = await anime_service.home()
    pool = home_data.get("trending_anime", []) + home_data.get("most_popular", []) + home_data.get("latest_episodes", [])
    if not pool:
        raise HTTPException(status_code=404, detail="No anime found")
    item = choice(pool)
    return {"success": True, "results": {"data": item}}


@router.get("/search", response_model=None)
async def search(
    q: str | None = Query(default=None, min_length=1, max_length=100),
    keyword: str | None = Query(default=None, min_length=1, max_length=100),
) -> dict:
    """Search anime."""

    query = q or keyword
    if not query:
        raise HTTPException(status_code=422, detail="Provide q or keyword")
    results = await anime_service.search(query)
    if keyword and not q:
        return {"success": True, "results": results}
    return {"success": True, "results": results}


@router.get("/search/suggest")
async def search_suggest(keyword: str = Query(..., min_length=1, max_length=100)) -> dict:
    """Return search suggestions."""

    return {"success": True, "results": await anime_service.search_suggest(keyword)}


@router.get("/filter")
async def filter_anime(
    type: str = "ALL",
    status: str = "ALL",
    rated: str = "ALL",
    score: str = "ALL",
    season: str = "ALL",
    language: str = "ALL",
    genres: str = "ALL",
    sort: str = "DEFAULT",
    page: int = 1,
    keyword: str | None = None,
) -> dict:
    """Best-effort filter endpoint backed by Animelok listing/search pages."""

    if keyword:
        return {"success": True, "results": {"totalPages": 1, "data": await anime_service.search(keyword)}}
    category = "home" if type == "ALL" and genres == "ALL" else str(type).lower()
    if category in {"all", "1", "2"}:
        category = "tv"
    if genres != "ALL":
        category = f"genre/{genres.split(',')[0].strip().lower()}"
    return {"success": True, "results": await anime_service.category(category, page)}


@router.get("/info")
async def info_query(id: str = Query(..., min_length=1)) -> dict:
    """HiAnime-style info endpoint."""

    return {"success": True, "results": await anime_service.info(id)}


@router.get("/info/{anime_id}")
async def info(anime_id: str) -> dict:
    """Return anime details."""

    return await anime_service.info(anime_id)


@router.get("/episodes/{anime_id}", response_model=list[Episode])
async def episodes(anime_id: str) -> list[dict]:
    """Return an anime's episode list."""

    return await anime_service.episodes(anime_id)


@router.get("/episodes/{anime_id}/hianime")
async def episodes_hianime(anime_id: str) -> dict:
    """HiAnime-style episode list response."""

    items = await anime_service.episodes(anime_id)
    return {
        "success": True,
        "results": {
            "totalEpisodes": len(items),
            "episodes": [
                {
                    "episode_no": item["number"],
                    "id": item["episode_id"],
                    "data_id": item["number"],
                    "jname": item.get("title"),
                    "title": item.get("title"),
                    "japanese_title": None,
                }
                for item in items
            ],
        },
    }


@router.get("/servers/{episode_id}", response_model=list[Server])
async def servers(episode_id: str, ep: int | None = Query(default=None)) -> list[dict]:
    """Return every server exposed by Animelok for an episode."""

    if ep is not None:
        episode_id = anime_service.episode_id_from_query(episode_id, ep)
    return await anime_service.servers(episode_id)


@router.get("/servers/{anime_id}/hianime")
async def servers_hianime(anime_id: str, ep: int = Query(default=1)) -> dict:
    """HiAnime-style servers endpoint backed by Animelok's full server list."""

    episode_id = anime_service.episode_id_from_query(anime_id, ep)
    servers = await anime_service.servers(episode_id)
    return {
        "success": True,
        "results": [
            {
                "type": item.get("type", "sub"),
                "data_id": item.get("data_id") or index,
                "server_id": item.get("server_id") or index,
                "serverName": item.get("server_name") or item.get("server"),
                "server_name": item.get("server_name") or item.get("server"),
                "url": item.get("url"),
            }
            for index, item in enumerate(servers, start=1)
        ],
    }


@router.get("/stream")
async def stream_query(
    id: str = Query(..., min_length=1),
    server: str = Query("multi"),
    type: str = Query("sub"),
    ep: int | None = Query(default=None),
) -> dict:
    """HiAnime-style stream endpoint."""

    episode_id = anime_service.episode_id_from_query(id, ep)
    results = await anime_service.stream(episode_id, server=server)
    servers = await anime_service.servers(episode_id)
    return {
        "success": True,
        "results": {
            "streamingLink": [
                {
                    "id": 1,
                    "type": results.get("type", type),
                    "link": {"file": results["stream_url"], "type": "hls"},
                    "tracks": results["subtitles"],
                    "audio_tracks": results.get("audio_tracks", []),
                    "intro": results["intro"],
                    "outro": results["outro"],
                    "server": results.get("server", server),
                    "qualities": results["qualities"],
                    "headers": results.get("headers", {}),
                }
            ],
            "servers": [
                {
                    "type": item.get("type", "sub"),
                    "data_id": item.get("data_id") or index,
                    "server_id": item.get("server_id") or index,
                    "server_name": item.get("server_name") or item.get("server"),
                    "serverName": item.get("server_name") or item.get("server"),
                    "url": item.get("url"),
                }
                for index, item in enumerate(servers, start=1)
            ],
        },
    }


@router.get("/stream/fallback")
async def stream_fallback(
    id: str = Query(..., min_length=1),
    server: str = Query("multi"),
    type: str = Query("sub"),
    ep: int | None = Query(default=None),
) -> dict:
    """Fallback endpoint mapped to the same Multi-only extractor."""

    return await stream_query(id=id, server=server, type=type, ep=ep)


@router.get("/stream/{episode_id}", response_model=StreamResponse)
async def stream(
    episode_id: str,
    ep: int | None = Query(default=None),
    server: str = Query("multi"),
) -> dict:
    """Extract a server stream."""

    if ep is not None:
        episode_id = anime_service.episode_id_from_query(episode_id, ep)
    results = await anime_service.stream(episode_id, server=server)
    return StreamResponse(results=StreamResults(**results)).model_dump()


@router.get("/schedule")
async def schedule(date: date = Query(...)) -> dict:
    """Return an empty schedule shell; Animelok does not expose a public schedule page."""

    return {"success": True, "results": []}


@router.get("/schedule/{anime_id}")
async def next_schedule(anime_id: str) -> dict:
    """Return next episode schedule when present in watch metadata."""

    data = await anime_service.info(anime_id)
    next_ep = data.get("nexrEpisode") or data.get("nextEpisode") or {}
    return {"success": True, "results": {"nextEpisodeSchedule": next_ep.get("airingAt") if isinstance(next_ep, dict) else None}}


@router.get("/qtip/{anime_id}")
async def qtip(anime_id: str) -> dict:
    """Return compact anime hover/info data."""

    data = await anime_service.info(anime_id)
    return {"success": True, "results": data}


@router.get("/producer/{producer:path}")
async def producer(producer: str, page: int = 1) -> dict:
    """Best-effort producer/studio listing."""

    return {"success": True, "results": await anime_service.category(f"producer/{producer}", page)}


@router.get("/character/list/{anime_id}")
async def character_list(anime_id: str) -> dict:
    """Character data is not exposed by Animelok's public pages."""

    return {"success": True, "results": {"currentPage": 1, "totalPages": 0, "data": []}}


@router.get("/character/{character_id}")
async def character(character_id: str) -> dict:
    """Character detail shell for API compatibility."""

    return {"success": True, "results": {"data": []}}


@router.get("/actors/{actor_id}")
async def actor(actor_id: str) -> dict:
    """Voice actor detail shell for API compatibility."""

    return {"success": True, "results": {"data": []}}


@router.get("/{category:path}")
async def category(category: str, page: int = 1) -> dict:
    """HiAnime-style category endpoint."""

    return {"success": True, "results": await anime_service.category(category, page)}
