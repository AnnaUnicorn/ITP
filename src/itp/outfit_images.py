"""Real outfit photographs for the wardrobe catalogue.

The wardrobe page shows one picture per recommended outfit.  This module finds
those pictures on the web, downloads the thumbnails into the local data
directory and hands the frontend a stable local URL, so the browser never links
a third-party CDN directly.

Providers
---------
``so`` (default, no key required)
    The mainland 360 image search JSON endpoint.  It answers a browser-looking
    ``User-Agent`` and returns ``list[]`` entries carrying ``img`` (original),
    ``thumb`` (their CDN thumbnail), ``title``, ``link``, ``site`` plus the
    original and thumbnail pixel sizes.  This is the only provider verified
    against the live service.
``unsplash``
    ``GET https://api.unsplash.com/search/photos`` with a ``Client-ID`` header.
``pixabay``
    ``GET https://pixabay.com/api/`` with a ``key`` query parameter.

The two keyed providers follow the official response shapes and are covered by
unit tests built on constructed payloads, but they were **not** verified against
the live services because no key was available.  Selecting one without a key
falls back to ``so``, and the reported provider always names the source that was
really used.

Caching
-------
``settings.data_dir/outfit_images`` holds the cache: ``img/<sha1>.<ext>`` keeps
the thumbnail files, named after the SHA-1 of the original image URL, and
``meta/<sha1>.json`` keeps one search result document per provider, query and
page.  Metadata lives for 7 days; ``refresh=True`` ignores it.  A failed
search writes a 15 minute negative entry so a burst of frontend requests cannot
hammer the source, and the page does not wait 8 seconds again immediately.  The
interface offers an explicit retry, which passes ``refresh=True`` and probes the
source again on purpose.

One cache entry always holds a full page of ``PAGE_SIZE`` candidates - their
remote URLs included - while only the pictures the caller actually asked for are
downloaded.  A card asking for 4 pictures and a detail dialog asking for 8 for
the same outfit therefore share a single search, and the dialog only fetches the
4 pictures the card did not need: the search count stays at one while the number
of downloaded thumbnails follows what is on screen.

``limit`` never takes part in the cache key, so it can never cause a second
search.  Growth is incremental: asking for more later tops up the local files
instead of starting over, and asking for fewer never downloads the difference.

Robustness
----------
A search never raises.  Every failure - timeout, connection error, HTTP error,
unparsable body - comes back as ``{"images": [], "error": "<reason>"}``.  At most
``MAX_IN_FLIGHT`` requests per source are in flight at once, one request's
thumbnails are fetched with ``DOWNLOAD_WORKERS`` threads so a cold card does not
wait for them one by one, each request times out after ``REQUEST_TIMEOUT``
seconds, 429 and 5xx answers get one short backoff retry, a single thumbnail
above ``MAX_IMAGE_BYTES`` is skipped, and images whose reported width or height
is below ``MIN_IMAGE_EDGE`` are dropped.  A thumbnail that fails only removes its
own picture: the rest of the page is still returned in candidate order.
"""

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from itp.config import Settings

PROVIDER_SO = "so"
PROVIDER_UNSPLASH = "unsplash"
PROVIDER_PIXABAY = "pixabay"
PROVIDER_IDS = (PROVIDER_SO, PROVIDER_UNSPLASH, PROVIDER_PIXABAY)
DEFAULT_PROVIDER = PROVIDER_SO
PROVIDER_LABELS = {
    PROVIDER_SO: "360 图片",
    PROVIDER_UNSPLASH: "Unsplash",
    PROVIDER_PIXABAY: "Pixabay",
}
# Keyed providers and the settings field holding their key.
PROVIDER_KEY_FIELDS = {
    PROVIDER_UNSPLASH: "unsplash_access_key",
    PROVIDER_PIXABAY: "pixabay_api_key",
}

SO_SEARCH_URL = "https://image.so.com/j"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/"

# 360 answers a browser-looking request; a bare client is refused.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 8.0
RETRY_BACKOFF_SECONDS = 0.5
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_IMAGE_EDGE = 200
META_TTL_SECONDS = 7 * 24 * 60 * 60
# A source that answered with an anti-bot page or an error stays refused for a
# while: re-probing it from every card would only deepen the block, and the UI
# offers an explicit retry that passes ``refresh=True``.
NEGATIVE_TTL_SECONDS = 15 * 60
# Requests in flight per source: searches and thumbnails of that source share
# this gate, so a page of cards cannot flood 360.
MAX_IN_FLIGHT = 4
# Threads used for one request's own thumbnails.  Slightly above the gate so the
# source stays busy while individual threads wait for their turn.
DOWNLOAD_WORKERS = 6

DEFAULT_LIMIT = 6
MIN_LIMIT = 1
MAX_LIMIT = 12
MIN_PAGE = 0
MAX_PAGE = 9

# Every cache entry holds one full page of this size, whatever ``limit`` the
# caller asks for, so two views of the same outfit share one search.
PAGE_SIZE = 12
IMAGE_DEFAULT_LIMIT = DEFAULT_LIMIT
IMAGE_MIN_LIMIT = MIN_LIMIT
IMAGE_MAX_LIMIT = PAGE_SIZE
IMAGE_MIN_PAGE = MIN_PAGE
IMAGE_MAX_PAGE = MAX_PAGE

CACHE_DIR_NAME = "outfit_images"
IMAGE_DIR_NAME = "img"
META_DIR_NAME = "meta"
IMAGE_NAME = re.compile(r"^[0-9a-f]{40}\.(jpg|jpeg|png|webp)$")
CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
DEFAULT_EXTENSION = "jpg"
DEFAULT_TITLE = "穿搭参考图"
DEFAULT_SITE = "image.so.com"

# One polite gate per source: concurrent outfit requests share these counters.
_SEMAPHORES = {provider: threading.Semaphore(MAX_IN_FLIGHT) for provider in PROVIDER_IDS}


# --------------------------------------------------------------------------- settings


def _provider_key(settings: Settings, provider: str) -> str:
    field = PROVIDER_KEY_FIELDS.get(provider)
    if not field:
        return ""
    secret = getattr(settings, field, None)
    read = getattr(secret, "get_secret_value", None)
    return read() if callable(read) else str(secret or "")


def resolve_provider(settings: Settings) -> tuple[str, str]:
    """Return the ``(provider id, label)`` actually used for a search.

    An unknown configured value, or a keyed provider without its key, degrades
    to the keyless default instead of failing, so the reported provider always
    describes the source that answered.
    """
    requested = (getattr(settings, "image_provider", "") or "").strip().lower()
    if requested not in PROVIDER_IDS:
        requested = DEFAULT_PROVIDER
    if requested in PROVIDER_KEY_FIELDS and not _provider_key(settings, requested).strip():
        requested = DEFAULT_PROVIDER
    return requested, PROVIDER_LABELS[requested]


def validate_provider_choice(value: str) -> str:
    """Normalise a provider id, or raise ``ValueError`` for an unknown one."""
    candidate = (value or "").strip().lower()
    if candidate not in PROVIDER_IDS:
        raise ValueError(f"image_provider must be one of {', '.join(PROVIDER_IDS)}")
    return candidate


# --------------------------------------------------------------------------- cache paths


def _cache_root(settings: Settings) -> Path:
    return Path(settings.data_dir) / CACHE_DIR_NAME


def _image_dir(settings: Settings) -> Path:
    return _cache_root(settings) / IMAGE_DIR_NAME


def _meta_dir(settings: Settings) -> Path:
    return _cache_root(settings) / META_DIR_NAME


def image_file_name(name: str) -> str | None:
    """Return ``name`` when it is a safe cache file name, otherwise ``None``.

    Only the SHA-1 names this module writes are accepted, and any separator or
    parent reference is refused before the name reaches the filesystem.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    return name if IMAGE_NAME.match(name) else None


def content_type_for(name: str) -> str:
    """Media type of a cached image name that already passed the whitelist."""
    return CONTENT_TYPES[Path(name).suffix.lower().lstrip(".")]


def cached_image_path(settings: Settings, name: str) -> Path | None:
    """Resolve a served image name inside the cache, or ``None`` when unusable."""
    safe = image_file_name(name)
    if safe is None:
        return None
    path = _image_dir(settings) / safe
    return path if path.is_file() else None


def _meta_key(provider: str, query: str, page: int) -> str:
    """Cache key of one search page.

    ``limit`` is deliberately absent: a card and a detail dialog asking for
    different numbers of pictures must share the same entry.
    """
    raw = f"{provider}\n{query}\n{page}".encode()
    return hashlib.sha1(raw).hexdigest()


def _read_meta(settings: Settings, provider: str, query: str, page: int) -> dict | None:
    """Return a fresh cache document, or ``None`` when missing or expired.

    An entry without a usable candidate list - for instance one written before
    thumbnails were fetched lazily - is treated as expired, so it is searched
    again instead of failing later.
    """
    path = _meta_dir(settings) / f"{_meta_key(provider, query, page)}.json"
    try:
        if not path.is_file():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    fetched = document.get("fetched_at")
    if not isinstance(fetched, (int, float)) or isinstance(fetched, bool):
        return None
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        return None
    if any(not _has_remote_url(item) for item in candidates):
        return None
    age = max(0.0, time.time() - fetched)
    ttl = NEGATIVE_TTL_SECONDS if document.get("error") else META_TTL_SECONDS
    return None if age > ttl else document


def _write_meta(
    settings: Settings,
    provider: str,
    query: str,
    page: int,
    *,
    error: str | None,
    candidates: list[dict],
) -> None:
    """Best-effort cache write; a read-only data directory is not an error.

    The whole page of candidates is stored with their remote URLs, whether or
    not their thumbnails have been downloaded yet.
    """
    document = {
        "provider": provider,
        "query": query,
        "page": page,
        "fetched_at": time.time(),
        "error": error,
        "candidates": candidates,
    }
    try:
        directory = _meta_dir(settings)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_meta_key(provider, query, page)}.json"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- HTTP


def _headers_for(provider: str, settings: Settings) -> dict[str, str]:
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    if provider == PROVIDER_UNSPLASH:
        headers["Authorization"] = f"Client-ID {_provider_key(settings, provider).strip()}"
    return headers


def _http_get_json(
    url: str, *, params: dict, headers: dict, timeout: float = REQUEST_TIMEOUT
) -> dict:
    """The real network boundary for a JSON search request."""
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise ValueError("search answer is not a JSON object")
    return body


def _http_get_bytes(
    url: str, *, headers: dict, limit: int = MAX_IMAGE_BYTES, timeout: float = REQUEST_TIMEOUT
) -> bytes | None:
    """The real network boundary for a thumbnail download.

    ``None`` means "over the byte budget": the body is read in chunks and
    abandoned as soon as it grows past ``limit``, so an oversized answer never
    has to fit in memory.
    """
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > limit:
                    return None
                chunks.append(chunk)
    return b"".join(chunks)


def _guarded(provider: str, operation):
    """Run one request behind the per-source concurrency gate."""
    with _SEMAPHORES[provider]:
        return operation()


def _with_retry(operation):
    """Run one request, retrying once after a short pause on 429 and 5xx."""
    try:
        return operation()
    except httpx.HTTPStatusError as exc:
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else 0
        if status != 429 and status < 500:
            raise
    time.sleep(RETRY_BACKOFF_SECONDS)
    return operation()


def _get_json(url: str, *, provider: str, params: dict, settings: Settings) -> dict:
    headers = _headers_for(provider, settings)
    return _with_retry(
        lambda: _guarded(provider, lambda: _http_get_json(url, params=params, headers=headers))
    )


def _get_bytes(url: str, *, provider: str, settings: Settings) -> bytes | None:
    headers = _headers_for(provider, settings)
    headers["Accept"] = "image/*,*/*;q=0.8"
    return _with_retry(lambda: _guarded(provider, lambda: _http_get_bytes(url, headers=headers)))


# --------------------------------------------------------------------------- helpers


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _hostname(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _candidate_count(limit: int) -> int:
    """Ask for a few more candidates than needed to survive local filtering."""
    return min(max(limit * 2, limit), 30)


def _outfit_query(outfit: dict) -> str:
    """The catalogue query of an outfit, or ``""`` when it has none.

    ``image_query`` is an internal catalogue field; falling back to the style
    and the name keeps an entry usable, and an entry with neither reports an
    error instead of searching for the bare word "穿搭".
    """
    query = outfit.get("image_query")
    if isinstance(query, str) and query.strip():
        return " ".join(query.split())
    parts = [
        part
        for part in (
            str(outfit.get("style") or "").strip(),
            str(outfit.get("name") or "").strip(),
        )
        if part
    ]
    if not parts:
        return ""
    return " ".join(f"{' '.join(parts)} 穿搭".split())


# --------------------------------------------------------------------------- providers


def _search_so(query: str, *, limit: int, page: int, settings: Settings) -> list[dict]:
    """Search 360 images; the only provider verified against the live service."""
    count = _candidate_count(limit)
    body = _get_json(
        SO_SEARCH_URL,
        provider=PROVIDER_SO,
        params={"q": query, "src": "srp", "sn": page * count, "pn": count},
        settings=settings,
    )
    items = body.get("list")
    if not isinstance(items, list):
        raise ValueError("360 image search answered without a list")
    candidates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        original = _text(item.get("img"))
        thumb = _text(item.get("thumb")) or original
        if not original or not thumb:
            continue
        link = _text(item.get("link"))
        candidates.append(
            {
                "original_url": original,
                "thumb_url": thumb,
                "source_url": link or original,
                "site": _text(item.get("site")) or _hostname(link) or DEFAULT_SITE,
                "title": _text(item.get("title")) or DEFAULT_TITLE,
                "width": _int(item.get("width")) or _int(item.get("thumbWidth")),
                "height": _int(item.get("height")) or _int(item.get("thumbHeight")),
                "creator": None,
                "license": None,
            }
        )
    return candidates


def _search_unsplash(query: str, *, limit: int, page: int, settings: Settings) -> list[dict]:
    """Search Unsplash.  Not verified live: it needs an access key."""
    body = _get_json(
        UNSPLASH_SEARCH_URL,
        provider=PROVIDER_UNSPLASH,
        params={"query": query, "per_page": _candidate_count(limit), "page": page + 1},
        settings=settings,
    )
    results = body.get("results")
    if not isinstance(results, list):
        raise ValueError("Unsplash answered without results")
    candidates = []
    for item in results:
        if not isinstance(item, dict):
            continue
        urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        original = _text(urls.get("regular")) or _text(urls.get("full")) or _text(urls.get("raw"))
        thumb = _text(urls.get("small")) or _text(urls.get("thumb")) or original
        if not original or not thumb:
            continue
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        candidates.append(
            {
                "original_url": original,
                "thumb_url": thumb,
                "source_url": _text(links.get("html")) or original,
                "site": "unsplash.com",
                "title": _text(item.get("description"))
                or _text(item.get("alt_description"))
                or DEFAULT_TITLE,
                "width": _int(item.get("width")),
                "height": _int(item.get("height")),
                "creator": _text(user.get("name")) or None,
                "license": "Unsplash License",
            }
        )
    return candidates


def _search_pixabay(query: str, *, limit: int, page: int, settings: Settings) -> list[dict]:
    """Search Pixabay.  Not verified live: it needs an API key."""
    body = _get_json(
        PIXABAY_SEARCH_URL,
        provider=PROVIDER_PIXABAY,
        params={
            "key": _provider_key(settings, PROVIDER_PIXABAY).strip(),
            "q": query,
            "per_page": max(3, _candidate_count(limit)),
            "page": page + 1,
            "image_type": "photo",
            "safesearch": "true",
        },
        settings=settings,
    )
    hits = body.get("hits")
    if not isinstance(hits, list):
        raise ValueError("Pixabay answered without hits")
    candidates = []
    for item in hits:
        if not isinstance(item, dict):
            continue
        original = _text(item.get("largeImageURL")) or _text(item.get("webformatURL"))
        thumb = _text(item.get("previewURL")) or _text(item.get("webformatURL")) or original
        if not original or not thumb:
            continue
        candidates.append(
            {
                "original_url": original,
                "thumb_url": thumb,
                "source_url": _text(item.get("pageURL")) or original,
                "site": "pixabay.com",
                "title": _text(item.get("tags")) or DEFAULT_TITLE,
                "width": _int(item.get("imageWidth")),
                "height": _int(item.get("imageHeight")),
                "creator": _text(item.get("user")) or None,
                "license": "Pixabay Content License",
            }
        )
    return candidates


_SEARCHERS = {
    PROVIDER_SO: _search_so,
    PROVIDER_UNSPLASH: _search_unsplash,
    PROVIDER_PIXABAY: _search_pixabay,
}


# --------------------------------------------------------------------------- thumbnails


def _existing_image(image_dir: Path, digest: str) -> Path | None:
    """A thumbnail already downloaded for this URL digest, whatever its suffix."""
    try:
        if not image_dir.is_dir():
            return None
        for path in sorted(image_dir.glob(f"{digest}.*")):
            if IMAGE_NAME.match(path.name) and path.is_file():
                return path
    except OSError:
        return None
    return None


def _extension_for(url: str, data: bytes) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if suffix in CONTENT_TYPES:
        return suffix
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return DEFAULT_EXTENSION


def _download_image(
    candidate: dict, *, provider: str, settings: Settings, image_dir: Path, digest: str
) -> Path | None:
    """Store one thumbnail under its URL digest, or ``None`` when unusable.

    The file name is always the locally computed digest, never anything the
    source returned, and an image above the byte budget is skipped instead of
    being written.
    """
    url = candidate.get("thumb_url") or candidate.get("original_url") or ""
    if not url:
        return None
    try:
        data = _get_bytes(url, provider=provider, settings=settings)
    except (httpx.HTTPError, ValueError, OSError):
        return None
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    path = image_dir / f"{digest}.{_extension_for(url, data)}"
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
    except OSError:
        return None
    return path if path.is_file() else None


def _digest(original_url: str) -> str:
    """The local identity of one picture: SHA-1 of its original URL."""
    return hashlib.sha1(original_url.encode()).hexdigest()


def _download_url(candidate: dict) -> str:
    """The remote URL a thumbnail is taken from."""
    return candidate.get("thumb_url") or candidate.get("original_url") or ""


def _has_remote_url(candidate: Any) -> bool:
    """Whether a cached candidate still carries everything a fetch needs."""
    if not isinstance(candidate, dict):
        return False
    return bool(candidate.get("original_url")) and bool(_download_url(candidate))


def _usable_candidates(candidates: list, *, limit: int) -> list[dict]:
    """Deduplicate, filter and normalise the source answer into one page.

    Normalising here means a candidate read back from the cache produces exactly
    the entry a fresh search would have produced.
    """
    usable: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        if len(usable) >= limit:
            break
        if not _has_remote_url(candidate):
            continue
        original = candidate["original_url"]
        if original in seen:
            continue
        width = _int(candidate.get("width"))
        height = _int(candidate.get("height"))
        if width < MIN_IMAGE_EDGE or height < MIN_IMAGE_EDGE:
            continue
        seen.add(original)
        usable.append(
            {
                "original_url": original,
                "thumb_url": _download_url(candidate),
                "source_url": candidate.get("source_url") or original,
                "site": candidate.get("site") or DEFAULT_SITE,
                "title": candidate.get("title") or DEFAULT_TITLE,
                "width": width,
                "height": height,
                "creator": candidate.get("creator") or None,
                "license": candidate.get("license") or None,
            }
        )
    return usable


def _public_image(candidate: dict, digest: str, stored: Path) -> dict[str, Any]:
    """The document the frontend consumes for one localised picture."""
    return {
        "id": digest,
        "url": f"/api/outfit-images/{stored.name}",
        "original_url": candidate["original_url"],
        "source_url": candidate["source_url"],
        "site": candidate["site"],
        "title": candidate["title"],
        "width": candidate["width"],
        "height": candidate["height"],
        "creator": candidate["creator"],
        "license": candidate["license"],
    }


def _download_many(
    pending: list[tuple[dict, str]], *, provider: str, settings: Settings, image_dir: Path
) -> dict[str, Path]:
    """Download the missing thumbnails in parallel and report what landed.

    Only failures are dropped: one unreachable thumbnail never hides the rest,
    and the results are keyed by digest so the caller can restore the source
    order.
    """
    if not pending:
        return {}

    def fetch(entry: tuple[dict, str]) -> tuple[str, Path | None]:
        candidate, digest = entry
        return digest, _download_image(
            candidate,
            provider=provider,
            settings=settings,
            image_dir=image_dir,
            digest=digest,
        )

    workers = min(DOWNLOAD_WORKERS, len(pending))
    stored: dict[str, Path] = {}
    if workers <= 1:
        for entry in pending:
            digest, path = fetch(entry)
            if path is not None:
                stored[digest] = path
        return stored
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="itp-outfit-image") as pool:
        futures = {pool.submit(fetch, entry): entry[1] for entry in pending}
        for future in as_completed(futures):
            digest = futures[future]
            try:
                _digest_result, path = future.result()
            except Exception:  # a broken worker only costs its own picture
                continue
            if path is not None:
                stored[digest] = path
    return stored


def _materialise(
    candidates: list[dict], *, limit: int, provider: str, settings: Settings
) -> list[dict[str, Any]]:
    """Return the first ``limit`` candidates as local pictures.

    Only the pictures this request needs are downloaded, missing ones are
    fetched in parallel, and files already on disk are reused - so asking for
    more later tops the page up instead of starting over.
    """
    image_dir = _image_dir(settings)
    wanted = candidates[:limit]
    resolved: list[tuple[dict, str, Path | None]] = []
    pending: list[tuple[dict, str]] = []
    for candidate in wanted:
        digest = _digest(candidate["original_url"])
        stored = _existing_image(image_dir, digest)
        if stored is None:
            pending.append((candidate, digest))
        resolved.append((candidate, digest, stored))
    if pending:
        downloaded = _download_many(
            pending, provider=provider, settings=settings, image_dir=image_dir
        )
        resolved = [
            (candidate, digest, stored if stored is not None else downloaded.get(digest))
            for candidate, digest, stored in resolved
        ]
    # Built in candidate order, so finishing order never reorders the result.
    return [
        _public_image(candidate, digest, stored)
        for candidate, digest, stored in resolved
        if stored is not None
    ]


def _fetch_candidates(provider: str, query: str, *, page: int, settings: Settings) -> list[dict]:
    """Search one whole page of candidates, without downloading anything."""
    searcher = _SEARCHERS.get(provider, _search_so)
    return _usable_candidates(
        searcher(query, limit=PAGE_SIZE, page=page, settings=settings), limit=PAGE_SIZE
    )


def _failure_reason(exc: Exception) -> str:
    """One Chinese sentence explaining why a search produced no pictures."""
    if isinstance(exc, httpx.TimeoutException):
        return "图片检索超时，请稍后重试"
    if isinstance(exc, httpx.HTTPStatusError):
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else 0
        if status == 429:
            return "图片来源限流，请稍后重试"
        if status >= 500:
            return "图片来源暂时不可用，请稍后重试"
        return "图片检索失败，请稍后重试"
    if isinstance(exc, httpx.HTTPError):
        return "无法连接到图片源，请检查网络后重试"
    if isinstance(exc, json.JSONDecodeError):
        # 360 answers its anti-crawler page with HTTP 200 and text/html, so a
        # body that is not JSON means the source is refusing us for a while.
        # The short negative cache below is the only backoff: retrying here
        # would only deepen the block.
        return "图片源暂时拒绝访问，请稍后重试"
    return "图片检索失败，请稍后重试"


def _cached_candidates(document: dict) -> list[dict]:
    """The candidate page of a cached document, defensively filtered."""
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if _has_remote_url(item)]


def search_outfit_images(
    outfit: dict,
    *,
    limit: int = IMAGE_DEFAULT_LIMIT,
    page: int = IMAGE_MIN_PAGE,
    refresh: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Return the cached or freshly fetched pictures for one outfit.

    The answer always carries ``outfit_id``, ``query``, ``provider``,
    ``provider_label``, ``cached``, ``error`` and ``images``.  It never raises:
    any failure comes back as an empty ``images`` list plus a Chinese ``error``
    sentence, together with a short negative cache entry.

    ``limit`` selects how many pictures of the cached page to return and, on a
    cold page, how many of them to download.  It never takes part in the cache
    key, so two callers asking for different numbers share one search.
    """
    settings = settings or Settings()
    outfit_id = str(outfit.get("id") or "")
    query = _outfit_query(outfit)
    provider, provider_label = resolve_provider(settings)
    result = {
        "outfit_id": outfit_id,
        "query": query,
        "provider": provider,
        "provider_label": provider_label,
        "cached": False,
        "error": None,
        "images": [],
    }
    try:
        limit = max(IMAGE_MIN_LIMIT, min(int(limit), IMAGE_MAX_LIMIT))
        page = max(IMAGE_MIN_PAGE, min(int(page), IMAGE_MAX_PAGE))
    except (TypeError, ValueError):
        limit, page = IMAGE_DEFAULT_LIMIT, IMAGE_MIN_PAGE
    if not query:
        result["error"] = "该穿搭方案还没有配置检索词"
        return result

    candidates: list[dict] = []
    search_error: str | None = None
    try:
        if not refresh:
            cached = _read_meta(settings, provider, query, page)
            if cached is not None:
                result["cached"] = True
                if cached.get("error"):
                    # A negative entry: do not touch the source again yet.
                    result["error"] = cached["error"]
                    return result
                result["images"] = _materialise(
                    _cached_candidates(cached),
                    limit=limit,
                    provider=provider,
                    settings=settings,
                )
                if not result["images"]:
                    result["error"] = "没有检索到可用的穿搭图片"
                return result
        candidates = _fetch_candidates(provider, query, page=page, settings=settings)
        result["images"] = _materialise(
            candidates, limit=limit, provider=provider, settings=settings
        )
        if not result["images"]:
            result["error"] = "没有检索到可用的穿搭图片"
        if not candidates:
            # A page nobody can use is cached briefly, like a failed search.
            search_error = result["error"]
    except Exception as exc:  # the endpoint must answer, whatever the source does
        search_error = _failure_reason(exc)
        result["error"] = search_error
        result["images"] = []
        candidates = []
    _write_meta(
        settings,
        provider,
        query,
        page,
        error=search_error,
        candidates=candidates,
    )
    return result
