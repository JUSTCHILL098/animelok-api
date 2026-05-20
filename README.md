# Animelok AniList API

FastAPI anime API that uses AniList IDs and AniList metadata publicly while mapping internally to Animelok for episodes, full server discovery, subtitles, intro/outro timestamps, and HLS stream extraction.

## Local Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the custom HTML docs:

```txt
http://127.0.0.1:8000/docs
```

## Example Endpoints

```txt
GET /api/search?q=Solo%20Leveling
GET /api/info/151807
GET /api/episodes/151807
GET /api/servers/151807?ep=1
GET /api/stream/151807?ep=1
GET /api/stream?id=151807&ep=1&server=multi&type=sub
```

## Stream Features

The servers endpoint returns every server Animelok exposes for the episode. The stream endpoint defaults to `multi`, but accepts `server=<name-or-id>` and parses the selected HLS master playlist for:

- `EXT-X-STREAM-INF` variants and quality metadata
- `EXT-X-MEDIA:TYPE=AUDIO` alternate audio tracks
- language name and code
- default and autoselect flags
- audio group ID
- audio playlist URI
- dub/sub inference from playlist metadata

## Vercel Deploy

This repository includes:

- `api/index.py`
- `vercel.json`
- `requirements.txt`

Deploy with Vercel after pushing the repository:

```bash
vercel
```

The deployed app serves the same custom docs page at `/docs`. FastAPI Swagger UI is disabled.
