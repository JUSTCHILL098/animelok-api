"""HTML and payload parsers for Animelok-like pages."""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from selectolax.parser import HTMLParser

from app.config import settings


def text(value: str | None) -> str:
    """Normalize visible text."""

    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def absolutize(url: str | None) -> str | None:
    """Resolve relative URLs and Next image wrappers."""

    if not url:
        return None
    cleaned = html.unescape(url)
    next_match = re.search(r"[?&]url=([^&]+)", cleaned)
    if next_match:
        cleaned = unquote(next_match.group(1))
    return urljoin(settings.normalized_base_url, cleaned)


def parse_cards(page_html: str) -> list[dict[str, Any]]:
    """Parse anime cards from search, home, and listing pages."""

    tree = HTMLParser(page_html)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in tree.css('a[href^="/anime/"]'):
        href = node.attributes.get("href", "")
        anime_id = href.rstrip("/").split("/anime/")[-1]
        if not anime_id or anime_id in seen:
            continue
        seen.add(anime_id)
        image = node.css_first("img")
        title_node = node.css_first("h3")
        title = text(title_node.text() if title_node else image.attributes.get("alt") if image else anime_id)
        poster = absolutize(image.attributes.get("src") if image else None)
        card_text = text(node.text())
        eps_match = re.search(r"(\d+|\?)\s*EPS", card_text, re.I)
        type_match = re.search(r"\b(TV|MOVIE|OVA|ONA|SPECIAL)\b", card_text, re.I)
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", card_text)
        results.append(
            {
                "anime_id": anime_id,
                "title": title,
                "japanese_title": None,
                "poster": poster,
                "episodes": int(eps_match.group(1)) if eps_match and eps_match.group(1).isdigit() else None,
                "type": type_match.group(1).upper() if type_match else None,
                "year": int(year_match.group(1)) if year_match else None,
            }
        )
    return results


def parse_genres(page_html: str) -> list[str]:
    """Extract genre names from visible navigation/footer links."""

    soup = BeautifulSoup(page_html, "lxml")
    genres: list[str] = []
    for anchor in soup.select('a[href*="/genre"], a[href*="genre="]'):
        name = text(anchor.get_text(" "))
        if name and name not in genres:
            genres.append(name)
    if genres:
        return genres
    defaults = [
        "Action",
        "Adventure",
        "Comedy",
        "Drama",
        "Fantasy",
        "Horror",
        "Mystery",
        "Romance",
        "School",
        "Sci-Fi",
        "Slice of Life",
        "Sports",
        "Supernatural",
    ]
    return defaults


def extract_watch_data(page_html: str) -> dict[str, Any] | None:
    """Extract the serialized watchDataPromise payload from a Next.js page."""

    match = re.search(r'\b\d+[a-z]?:({\\"anime\\":.*?})\\n"\]\)</script>', page_html, re.S)
    if not match:
        match = re.search(r'({\\"anime\\":.*?\\"isAdFree\\":(?:true|false)})', page_html, re.S)
    if not match:
        return None
    raw = match.group(1)
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape")
        decoded = decoded.replace('"$undefined"', "null")
        return json.loads(decoded)
    except json.JSONDecodeError:
        return None


def parse_detail_from_watch(anime_id: str, page_html: str) -> dict[str, Any]:
    """Build a detail object from watch page payload and visible markup."""

    payload = extract_watch_data(page_html) or {}
    anime = payload.get("anime") or {}
    cover = anime.get("coverImage") or {}
    title = anime.get("title") or anime.get("slug") or anime_id
    language_episodes = anime.get("languageEpisodes") or {}
    max_episodes = max([int(v) for v in language_episodes.values() if isinstance(v, int)] or [anime.get("totalEpisodes") or 0])
    return {
        "anime_id": anime_id,
        "slug": anime.get("slug") or anime_id,
        "source_id": anime.get("id"),
        "anilist_id": anime.get("anilistId"),
        "mal_id": anime.get("malId"),
        "hianime_id": anime.get("hianimeId"),
        "title": title,
        "japanese_title": None,
        "poster": cover.get("large") or cover.get("hianime") or cover.get("medium"),
        "synopsis": text(BeautifulSoup(page_html, "lxml").find("meta", attrs={"name": "description"}).get("content", "") if BeautifulSoup(page_html, "lxml").find("meta", attrs={"name": "description"}) else ""),
        "genres": parse_genres(page_html),
        "studios": [],
        "producers": [],
        "seasons": anime.get("seasons") or [],
        "related_anime": anime.get("relations") or [],
        "recommended_anime": anime.get("recommendations") or [],
        "available_languages": anime.get("availableLanguages") or [],
        "episode_counts": language_episodes,
        "total_episodes": max_episodes,
        "type": anime.get("format"),
        "year": anime.get("year"),
    }


def section_cards(page_html: str, heading: str) -> list[dict[str, Any]]:
    """Best-effort section parser using headings near card grids."""

    lower = page_html.lower()
    index = lower.find(heading.lower())
    if index < 0:
        return []
    next_index = len(page_html)
    for marker in ["trending", "latest", "top airing", "most popular", "recommended", "movies"]:
        if marker == heading.lower():
            continue
        found = lower.find(marker, index + len(heading))
        if found > index:
            next_index = min(next_index, found)
    return parse_cards(page_html[index:next_index])[:24]
