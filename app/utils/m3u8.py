"""M3U8 playlist parsing helpers."""

from __future__ import annotations

import re
from urllib.parse import urljoin


def parse_attribute_list(value: str) -> dict[str, str]:
    """Parse an HLS attribute list without splitting quoted commas."""

    attributes: dict[str, str] = {}
    index = 0
    length = len(value)
    while index < length:
        while index < length and value[index] in " ,":
            index += 1
        key_start = index
        while index < length and value[index] != "=":
            index += 1
        if index >= length:
            break
        key = value[key_start:index].strip()
        index += 1
        if index < length and value[index] == '"':
            index += 1
            chars: list[str] = []
            while index < length:
                char = value[index]
                if char == '"':
                    index += 1
                    break
                chars.append(char)
                index += 1
            raw = "".join(chars)
        else:
            value_start = index
            while index < length and value[index] != ",":
                index += 1
            raw = value[value_start:index].strip()
        if key:
            attributes[key.upper()] = raw
        while index < length and value[index] != ",":
            index += 1
        if index < length and value[index] == ",":
            index += 1
    return attributes


def _bool_attr(value: str | None) -> bool:
    return str(value or "").upper() == "YES"


def _audio_kind(name: str | None, code: str | None, characteristics: str | None) -> str | None:
    """Infer a friendly audio role from playlist metadata when possible."""

    haystack = " ".join(part for part in [name, code, characteristics] if part).lower()
    if any(token in haystack for token in ["dub", "english", "eng", "en"]):
        return "dub"
    if any(token in haystack for token in ["sub", "japanese", "jpn", "japanese audio", "ja"]):
        return "sub"
    return None


def parse_master_playlist(master_url: str, playlist: str) -> dict[str, list[dict[str, object]] | bool]:
    """Parse variants and alternate audio tracks from an HLS master playlist."""

    qualities: list[dict[str, object]] = []
    audio_tracks: list[dict[str, object]] = []
    lines = [line.strip() for line in playlist.splitlines() if line.strip()]
    is_master = False

    for index, line in enumerate(lines):
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = parse_attribute_list(line.split(":", 1)[1])
            if attrs.get("TYPE", "").upper() != "AUDIO":
                continue
            is_master = True
            uri = attrs.get("URI")
            name = attrs.get("NAME") or attrs.get("LANGUAGE") or "Audio"
            code = attrs.get("LANGUAGE")
            track: dict[str, object] = {
                "language": name,
                "name": name,
                "code": code,
                "default": _bool_attr(attrs.get("DEFAULT")),
                "auto_select": _bool_attr(attrs.get("AUTOSELECT")),
                "group_id": attrs.get("GROUP-ID"),
                "uri": urljoin(master_url, uri) if uri else None,
                "metadata": attrs,
            }
            kind = _audio_kind(name, code, attrs.get("CHARACTERISTICS"))
            if kind:
                track["type"] = kind
            audio_tracks.append(track)
            continue

        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        is_master = True
        attrs = parse_attribute_list(line.split(":", 1)[1])
        uri = lines[index + 1] if index + 1 < len(lines) and not lines[index + 1].startswith("#") else ""
        resolution = attrs.get("RESOLUTION")
        height = None
        if resolution:
            match = re.match(r"\d+x(\d+)", resolution)
            height = int(match.group(1)) if match else None
        bandwidth = int(attrs["BANDWIDTH"]) if attrs.get("BANDWIDTH", "").isdigit() else None
        qualities.append(
            {
                "quality": f"{height}p" if height else "auto",
                "url": urljoin(master_url, uri) if uri else master_url,
                "bandwidth": bandwidth,
                "audio_group_id": attrs.get("AUDIO"),
                "metadata": attrs,
            }
        )

    if not qualities and "#EXTM3U" in playlist:
        qualities.append({"quality": "auto", "url": master_url, "bandwidth": None, "audio_group_id": None, "metadata": {}})

    return {"qualities": qualities, "audio_tracks": audio_tracks, "is_master": is_master}


def parse_qualities(master_url: str, playlist: str) -> list[dict[str, str | int | None]]:
    """Parse variants from a master m3u8 playlist."""

    return parse_master_playlist(master_url, playlist)["qualities"]  # type: ignore[return-value]
