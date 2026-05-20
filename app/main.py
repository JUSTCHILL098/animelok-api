"""FastAPI entrypoint."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, ORJSONResponse

from app.config import settings
from app.middleware import RateLimitMiddleware
from app.routes.anime import router as anime_router
from app.utils.exceptions import NotFoundError, ScraperError, StreamExtractionError
from app.utils.http import http_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
START_TIME = time.monotonic()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start and stop shared resources."""

    await http_client.start()
    try:
        yield
    finally:
        await http_client.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Fast async anime scraping API. Streaming endpoints only expose the multi server.",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(anime_router)


@app.get("/", tags=["status"])
async def status() -> dict[str, Any]:
    """Return API status, version, and uptime."""

    return {
        "success": True,
        "status": "ok",
        "version": settings.version,
        "uptime": round(time.monotonic() - START_TIME, 3),
    }


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def html_docs() -> str:
    """Return custom HTML API documentation instead of Swagger UI."""

    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Animelok AniList API Docs</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #16181d;
      --muted: #5e6675;
      --line: #d9dee8;
      --accent: #0f766e;
      --accent-soft: #d9f3ef;
      --code: #101828;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
      line-height: 1.55;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .wrap {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
    }
    .hero {
      padding: 40px 0 28px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 5vw, 3.4rem);
      line-height: 1.05;
      letter-spacing: 0;
    }
    .lead {
      max-width: 760px;
      margin: 0;
      color: var(--muted);
      font-size: 1.05rem;
    }
    main {
      padding: 28px 0 56px;
    }
    section {
      padding: 22px 0;
      border-bottom: 1px solid var(--line);
    }
    h2 {
      margin: 0 0 14px;
      font-size: 1.35rem;
    }
    h3 {
      margin: 18px 0 8px;
      font-size: 1rem;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    code, pre {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }
    code {
      padding: 2px 5px;
      border-radius: 5px;
      background: var(--accent-soft);
      color: #0b514b;
      overflow-wrap: anywhere;
    }
    pre {
      margin: 10px 0 0;
      padding: 14px;
      overflow-x: auto;
      border-radius: 8px;
      color: #f8fafc;
      background: var(--code);
      font-size: .9rem;
    }
    .method {
      display: inline-flex;
      align-items: center;
      height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      font-size: .78rem;
      font-weight: 700;
      margin-right: 8px;
    }
    ul {
      padding-left: 20px;
      margin: 8px 0 0;
    }
    a {
      color: var(--accent);
      text-decoration-thickness: 1px;
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap hero">
      <h1>Animelok AniList API</h1>
      <p class="lead">Use AniList IDs for public API calls while the service maps internally to Animelok for episodes, servers, HLS streams, subtitles, intro/outro timestamps, and multi-audio extraction.</p>
    </div>
  </header>
  <main class="wrap">
    <section>
      <h2>Base URL</h2>
      <p>Local development: <code>http://127.0.0.1:8000</code></p>
      <p>Vercel: use your deployment URL after publishing.</p>
    </section>

    <section>
      <h2>Core Endpoints</h2>
      <div class="grid">
        <div class="card">
          <h3><span class="method">GET</span><code>/api/search?q=Solo%20Leveling</code></h3>
          <p>Searches AniList and returns normalized AniList IDs and metadata.</p>
        </div>
        <div class="card">
          <h3><span class="method">GET</span><code>/api/info/151807</code></h3>
          <p>Returns AniList metadata, plus internal Animelok availability details when mapped.</p>
        </div>
        <div class="card">
          <h3><span class="method">GET</span><code>/api/episodes/151807</code></h3>
          <p>Maps AniList ID to Animelok internally and returns public AniList-based episode IDs.</p>
        </div>
        <div class="card">
          <h3><span class="method">GET</span><code>/api/stream/151807?ep=1</code></h3>
          <p>Extracts the Animelok Multi HLS source for the AniList anime and episode number.</p>
        </div>
      </div>
    </section>

    <section>
      <h2>Stream Response</h2>
      <p>The stream endpoint parses the HLS master playlist and includes all alternate audio tracks from <code>#EXT-X-MEDIA:TYPE=AUDIO</code>.</p>
      <pre>{
  "success": true,
  "results": {
    "stream_url": "https://.../master.m3u8",
    "qualities": [
      { "quality": "1080p", "url": "https://...", "audio_group_id": "audio" }
    ],
    "subtitles": [
      { "label": "English", "kind": "subtitles", "url": "https://..." }
    ],
    "audio_tracks": [
      {
        "language": "Japanese",
        "name": "Japanese",
        "code": "jpn",
        "default": false,
        "auto_select": true,
        "group_id": "audio",
        "uri": "https://.../audio_jpn.m3u8",
        "type": "sub"
      },
      {
        "language": "English",
        "name": "English",
        "code": "eng",
        "default": false,
        "auto_select": true,
        "group_id": "audio",
        "uri": "https://.../audio_eng.m3u8",
        "type": "dub"
      }
    ],
    "intro": { "start": 2, "end": 92 },
    "outro": { "start": 1325, "end": 1413 }
  }
}</pre>
    </section>

    <section>
      <h2>Compatibility</h2>
      <ul>
        <li><code>/api/stream?id=151807&amp;ep=1&amp;server=multi&amp;type=sub</code> is still supported.</li>
        <li>Provider IDs are used internally only for mapping and extraction.</li>
        <li><code>/openapi.json</code> remains available for tools, but this page replaces Swagger UI.</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""


@app.exception_handler(NotFoundError)
async def not_found_handler(_: Request, exc: NotFoundError) -> ORJSONResponse:
    return ORJSONResponse({"success": False, "error": str(exc)}, status_code=404)


@app.exception_handler(StreamExtractionError)
async def stream_error_handler(_: Request, exc: StreamExtractionError) -> ORJSONResponse:
    return ORJSONResponse({"success": False, "error": str(exc)}, status_code=502)


@app.exception_handler(ScraperError)
async def scraper_error_handler(_: Request, exc: ScraperError) -> ORJSONResponse:
    logger.warning("scraper error: %s", exc)
    return ORJSONResponse({"success": False, "error": str(exc)}, status_code=502)


@app.exception_handler(Exception)
async def generic_error_handler(_: Request, exc: Exception) -> ORJSONResponse:
    logger.exception("unhandled error")
    return ORJSONResponse({"success": False, "error": "Internal server error"}, status_code=500)
