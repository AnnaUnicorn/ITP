"""Offline tests for the outfit photo search, cache and HTTP contract.

Every network call is replaced by :class:`FakeHttp`, which stands in for the two
functions in ``itp.outfit_images`` that touch httpx.  The tests therefore cover
the provider parsing, the cache and the API surface without leaving the machine.
"""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from itp import outfit_images
from itp.api import create_app
from itp.config import Settings
from itp.wardrobe import CATALOG, recommend_outfits

SO_URL = "https://image.so.com/j"
UNSPLASH_URL = "https://api.unsplash.com/search/photos"
PIXABAY_URL = "https://pixabay.com/api/"
CJK = range(0x4E00, 0x9FFF + 1)


# --------------------------------------------------------------------------- doubles


class FakeHttp:
    """Stands in for ``outfit_images._http_get_json`` and ``._http_get_bytes``."""

    def __init__(self):
        self.json_calls: list[dict] = []
        self.image_calls: list[str] = []
        self.json_response: dict | object = {"list": []}
        self.image_response: bytes | None = b"jpeg-bytes"
        self.image_handler: object = None
        self.json_error: Exception | None = None
        self.image_error: Exception | None = None
        self.json_errors: list[Exception] = []

    def get_json(self, url, *, params, headers, timeout=None):
        self.json_calls.append({"url": url, "params": dict(params), "headers": dict(headers)})
        if self.json_errors:
            raise self.json_errors.pop(0)
        if self.json_error is not None:
            raise self.json_error
        response = self.json_response
        return response(url, dict(params)) if callable(response) else response

    def get_bytes(self, url, *, headers, limit=None, timeout=None):
        self.image_calls.append(url)
        if self.image_error is not None:
            raise self.image_error
        handler = self.image_handler
        return handler(url) if callable(handler) else self.image_response


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(outfit_images, "_http_get_json", fake.get_json)
    monkeypatch.setattr(outfit_images, "_http_get_bytes", fake.get_bytes)
    monkeypatch.setattr(outfit_images, "RETRY_BACKOFF_SECONDS", 0)
    return fake


def variant(settings: Settings, **overrides) -> Settings:
    """A copy of ``settings`` with a few fields replaced."""
    return Settings(_env_file=None, **(settings.model_dump() | overrides))


def client_for(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, start_worker=False), base_url="http://localhost:8000")


def status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", SO_URL)
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=httpx.Response(status, request=request)
    )


def so_item(url, *, width=800, height=600, title="初秋通勤", site="baidu.com"):
    return {
        "title": title,
        "img": url,
        "thumb": f"{url}.thumb.jpg",
        "thumbWidth": width,
        "thumbHeight": height,
        "width": width,
        "height": height,
        "link": "https://www.baidu.com/note/1",
        "site": site,
    }


def outfit_by_id(outfit_id: str) -> dict:
    return next(entry for entry in CATALOG if entry["id"] == outfit_id)


def digest_of(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def meta_path(settings: Settings, outfit: dict) -> Path:
    key = outfit_images._meta_key("so", outfit["image_query"], 0)
    return settings.data_dir / "outfit_images" / "meta" / f"{key}.json"


def read_meta(settings: Settings, outfit: dict) -> dict:
    return json.loads(meta_path(settings, outfit).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- catalogue


def test_catalogue_queries_are_unique_chinese_and_stay_internal():
    assert len(CATALOG) == 18
    queries = [entry["image_query"] for entry in CATALOG]
    assert all(isinstance(query, str) and query.strip() for query in queries)
    assert all(3 <= len(query.split()) <= 6 for query in queries)
    assert len(set(queries)) == len(queries)
    assert all(any(ord(char) in CJK for char in query) for query in queries)
    # Regression: the public recommendation document must not leak the field.
    public = recommend_outfits(None)
    assert public and all("image_query" not in entry for entry in public)
    assert "image_query" not in json.dumps(public, ensure_ascii=False)


def test_outfit_without_a_query_reports_an_error_without_searching(http, settings):
    body = outfit_images.search_outfit_images({"id": "unknown"}, settings=settings)
    assert body["query"] == ""
    assert body["images"] == []
    assert body["error"] == "该穿搭方案还没有配置检索词"
    assert http.json_calls == []


# --------------------------------------------------------------------------- 360 provider


def test_so_provider_maps_filters_dedupes_and_limits(http, settings):
    http.json_response = {
        "list": [
            so_item("https://img.example.com/a.jpg", title="通勤大衣"),
            so_item("https://img.example.com/small.jpg", width=120, height=600),
            so_item("https://img.example.com/a.jpg", title="重复"),
            {"img": "https://img.example.com/nosize.jpg", "thumb": "https://x/nosize.t.jpg"},
            {"title": "没有图片"},
            "not a dict",
            so_item("https://img.example.com/d.jpg", width=900, height=700, title=None, site=None),
        ]
    }
    outfit = outfit_by_id("soft-tailoring")
    body = outfit_images.search_outfit_images(outfit, settings=settings)

    assert body["outfit_id"] == "soft-tailoring"
    assert body["query"] == outfit["image_query"]
    assert body["provider"] == "so" and body["provider_label"] == "360 图片"
    assert body["cached"] is False and body["error"] is None
    assert [image["original_url"] for image in body["images"]] == [
        "https://img.example.com/a.jpg",
        "https://img.example.com/d.jpg",
    ]

    first = body["images"][0]
    digest = hashlib.sha1(b"https://img.example.com/a.jpg").hexdigest()
    assert first["id"] == digest
    assert first["url"] == f"/api/outfit-images/{digest}.jpg"
    assert (first["width"], first["height"]) == (800, 600)
    assert first["site"] == "baidu.com" and first["title"] == "通勤大衣"
    assert first["source_url"] == "https://www.baidu.com/note/1"
    assert first["creator"] is None and first["license"] is None

    # Sparse entries fall back to named defaults rather than None.
    sparse = body["images"][1]
    assert sparse["title"] == outfit_images.DEFAULT_TITLE
    assert sparse["site"] == "www.baidu.com"

    call = http.json_calls[0]
    assert call["url"] == SO_URL
    assert call["params"]["q"] == outfit["image_query"]
    # The source is asked for a whole page, never for the caller's limit.
    assert (call["params"]["sn"], call["params"]["pn"], call["params"]["src"]) == (0, 24, "srp")
    assert "Chrome" in call["headers"]["User-Agent"]

    limited = outfit_images.search_outfit_images(outfit, limit=1, refresh=True, settings=settings)
    assert len(limited["images"]) == 1


def test_page_offset_is_forwarded_to_the_source(http, settings):
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    outfit_images.search_outfit_images(CATALOG[0], limit=4, page=2, settings=settings)
    params = http.json_calls[0]["params"]
    assert params["sn"] == 2 * params["pn"]  # page windows never overlap
    assert params["pn"] >= outfit_images.PAGE_SIZE


def test_missing_list_is_reported_not_raised(http, settings):
    http.json_response = {"unexpected": True}
    body = outfit_images.search_outfit_images(CATALOG[0], settings=settings)
    assert body["images"] == []
    assert body["error"] == "图片检索失败，请稍后重试"


# --------------------------------------------------------------------------- cache


def test_second_call_is_cached_refresh_bypasses_and_ttl_expires(http, settings):
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    outfit = CATALOG[0]

    first = outfit_images.search_outfit_images(outfit, settings=settings)
    assert first["cached"] is False and len(http.json_calls) == 1

    second = outfit_images.search_outfit_images(outfit, settings=settings)
    assert second["cached"] is True and len(http.json_calls) == 1
    assert second["images"] == first["images"] and second["error"] is None

    outfit_images.search_outfit_images(outfit, refresh=True, settings=settings)
    assert len(http.json_calls) == 2

    meta_dir = settings.data_dir / "outfit_images" / "meta"
    document = json.loads(next(meta_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert document["provider"] == "so" and document["query"] == outfit["image_query"]
    document["fetched_at"] = time.time() - outfit_images.META_TTL_SECONDS - 60
    next(meta_dir.glob("*.json")).write_text(json.dumps(document), encoding="utf-8")

    outfit_images.search_outfit_images(outfit, settings=settings)
    assert len(http.json_calls) == 3


def test_limit_only_slices_one_cached_page(http, settings):
    """A card (limit=4) and a detail dialog (limit=8) must share one search."""
    http.json_response = {
        "list": [so_item(f"https://img.example.com/{index}.jpg") for index in range(12)]
    }
    outfit = CATALOG[0]

    card = outfit_images.search_outfit_images(outfit, limit=4, settings=settings)
    assert card["cached"] is False
    assert len(card["images"]) == 4
    assert len(http.json_calls) == 1

    dialog = outfit_images.search_outfit_images(outfit, limit=8, settings=settings)
    assert dialog["cached"] is True
    assert len(dialog["images"]) == 8
    assert len(http.json_calls) == 1  # no second search for the same outfit
    assert dialog["images"][:4] == card["images"]
    assert [image["id"] for image in dialog["images"]][:4] == [
        image["id"] for image in card["images"]
    ]
    assert dialog["error"] is None

    # The cache key carries provider, query and page only - never the limit.
    metas = list((settings.data_dir / "outfit_images" / "meta").glob("*.json"))
    assert len(metas) == 1
    expected = hashlib.sha1(f"so\n{outfit['image_query']}\n0".encode()).hexdigest()
    assert metas[0].stem == expected
    document = json.loads(metas[0].read_text(encoding="utf-8"))
    assert "limit" not in document
    assert len(document["candidates"]) == 12


def test_downloads_are_lazy_and_incremental(http, settings):
    """Cold limit=4 fetches 4 files but remembers the whole page of 12."""
    urls = [f"https://img.example.com/{index}.jpg" for index in range(12)]
    http.json_response = {"list": [so_item(url) for url in urls]}
    http.image_handler = lambda url: f"bytes:{url}".encode()
    outfit = CATALOG[0]

    card = outfit_images.search_outfit_images(outfit, limit=4, settings=settings)
    assert len(card["images"]) == 4
    assert len(http.json_calls) == 1
    assert len(http.image_calls) == 4  # only the pictures the card shows
    assert [image["id"] for image in card["images"]] == [digest_of(url) for url in urls[:4]]

    document = read_meta(settings, outfit)
    assert len(document["candidates"]) == 12  # the whole page is remembered
    assert document["candidates"][4]["thumb_url"] == f"{urls[4]}.thumb.jpg"
    assert document["candidates"][4]["original_url"] == urls[4]

    dialog = outfit_images.search_outfit_images(outfit, limit=8, settings=settings)
    assert dialog["cached"] is True
    assert len(dialog["images"]) == 8
    assert len(http.json_calls) == 1
    assert len(http.image_calls) == 8  # exactly the 4 the card was missing
    assert dialog["images"][:4] == card["images"]
    assert [image["id"] for image in dialog["images"]] == [digest_of(url) for url in urls[:8]]

    # Asking for less again downloads nothing at all.
    again = outfit_images.search_outfit_images(outfit, limit=4, settings=settings)
    assert again["cached"] is True and again["images"] == card["images"]
    assert len(http.image_calls) == 8

    # The rest of the remembered page is topped up on demand.
    full = outfit_images.search_outfit_images(outfit, limit=12, settings=settings)
    assert len(full["images"]) == 12
    assert [image["id"] for image in full["images"]] == [digest_of(url) for url in urls]
    assert len(http.image_calls) == 12
    assert len(http.json_calls) == 1

    # Every file holds its own picture, not a neighbour's.
    for image, url in zip(full["images"], urls, strict=True):
        name = image["url"].rsplit("/", 1)[-1]
        stored = settings.data_dir / "outfit_images" / "img" / name
        assert stored.read_bytes() == f"bytes:{url}.thumb.jpg".encode()


def test_parallel_downloads_keep_candidate_order(http, settings):
    """Thumbnails finish out of order but are reported in candidate order."""
    urls = [f"https://img.example.com/{index}.jpg" for index in range(12)]

    def slow(url):
        index = int(url.split("/")[-1].split(".")[0])
        time.sleep((12 - index) * 0.01)  # first candidate finishes last
        return f"bytes:{url}".encode()

    http.json_response = {"list": [so_item(url) for url in urls]}
    http.image_handler = slow
    body = outfit_images.search_outfit_images(CATALOG[0], limit=12, settings=settings)

    assert body["error"] is None
    assert len(http.image_calls) == 12
    assert [image["id"] for image in body["images"]] == [digest_of(url) for url in urls]
    assert [image["title"] for image in body["images"]] == ["初秋通勤"] * 12
    for image, url in zip(body["images"], urls, strict=True):
        name = image["url"].rsplit("/", 1)[-1]
        stored = settings.data_dir / "outfit_images" / "img" / name
        assert stored.read_bytes() == f"bytes:{url}.thumb.jpg".encode()


def test_a_short_result_set_is_returned_as_is(http, settings):
    http.json_response = {
        "list": [so_item(f"https://img.example.com/{index}.jpg") for index in range(3)]
    }
    body = outfit_images.search_outfit_images(CATALOG[0], limit=8, settings=settings)
    assert len(body["images"]) == 3
    assert body["error"] is None
    assert len(http.image_calls) == 3

    wider = outfit_images.search_outfit_images(CATALOG[0], limit=12, settings=settings)
    assert wider["cached"] is True
    assert len(wider["images"]) == 3
    assert len(http.json_calls) == 1
    assert len(http.image_calls) == 3  # nothing left to top up


def test_each_page_keeps_its_own_cache_entry(http, settings):
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    outfit_images.search_outfit_images(CATALOG[0], page=0, settings=settings)
    outfit_images.search_outfit_images(CATALOG[0], page=1, settings=settings)
    assert len(http.json_calls) == 2
    metas = list((settings.data_dir / "outfit_images" / "meta").glob("*.json"))
    assert len(metas) == 2
    outfit_images.search_outfit_images(CATALOG[0], page=0, settings=settings)
    assert len(http.json_calls) == 2


def test_a_metadata_document_without_remote_urls_is_treated_as_stale(http, settings):
    """An entry written before lazy downloads is refreshed, not trusted."""
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    outfit = CATALOG[0]
    path = meta_path(settings, outfit)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "provider": "so",
                "query": outfit["image_query"],
                "page": 0,
                "fetched_at": time.time(),
                "error": None,
                "images": [{"id": "a" * 40, "url": f"/api/outfit-images/{'a' * 40}.jpg"}],
            }
        ),
        encoding="utf-8",
    )

    body = outfit_images.search_outfit_images(outfit, settings=settings)
    assert body["cached"] is False
    assert len(http.json_calls) == 1
    assert len(body["images"]) == 1
    rewritten = read_meta(settings, outfit)
    assert len(rewritten["candidates"]) == 1 and "images" not in rewritten


def test_a_candidate_page_without_download_urls_is_treated_as_stale(http, settings):
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    outfit = CATALOG[0]
    path = meta_path(settings, outfit)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "provider": "so",
                "query": outfit["image_query"],
                "page": 0,
                "fetched_at": time.time(),
                "error": None,
                "candidates": [{"original_url": "", "thumb_url": ""}, "not a dict"],
            }
        ),
        encoding="utf-8",
    )

    body = outfit_images.search_outfit_images(outfit, settings=settings)
    assert body["cached"] is False
    assert len(http.json_calls) == 1
    assert len(body["images"]) == 1


def test_thumbnails_are_stored_once_and_oversized_ones_are_skipped(http, settings, monkeypatch):
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    outfit = CATALOG[0]

    body = outfit_images.search_outfit_images(outfit, settings=settings)
    digest = body["images"][0]["id"]
    stored = settings.data_dir / "outfit_images" / "img" / f"{digest}.jpg"
    assert stored.is_file()
    assert stored.read_bytes() == http.image_response
    assert len(http.image_calls) == 1

    # A refresh reuses the file on disk instead of downloading it again.
    outfit_images.search_outfit_images(outfit, refresh=True, settings=settings)
    assert len(http.image_calls) == 1

    monkeypatch.setattr(outfit_images, "MAX_IMAGE_BYTES", 4)
    http.json_response = {"list": [so_item("https://img.example.com/big.jpg")]}
    oversized = outfit_images.search_outfit_images(outfit, limit=3, refresh=True, settings=settings)
    assert oversized["images"] == []
    assert oversized["error"] == "没有检索到可用的穿搭图片"
    assert len(http.image_calls) == 2
    big_digest = digest_of("https://img.example.com/big.jpg")
    assert not list((settings.data_dir / "outfit_images" / "img").glob(f"{big_digest}.*"))


def test_one_failed_download_only_drops_that_image(http, settings):
    urls = [f"https://img.example.com/{index}.jpg" for index in range(3)]

    def flaky(url):
        if url.endswith("0.jpg.thumb.jpg"):
            raise httpx.ConnectError("cdn down")
        if url.endswith("1.jpg.thumb.jpg"):
            return None  # over the byte budget
        return f"bytes:{url}".encode()

    http.json_response = {"list": [so_item(url) for url in urls]}
    http.image_handler = flaky
    body = outfit_images.search_outfit_images(CATALOG[0], limit=3, settings=settings)

    assert body["error"] is None  # the survivors are still a valid answer
    assert [image["id"] for image in body["images"]] == [digest_of(urls[2])]
    assert len(http.json_calls) == 1

    # The page keeps all three candidates, so the two gaps can be refilled
    # without another search once the CDN recovers.
    http.image_handler = lambda url: f"bytes:{url}".encode()
    recovered = outfit_images.search_outfit_images(CATALOG[0], limit=3, settings=settings)
    assert recovered["cached"] is True
    assert [image["id"] for image in recovered["images"]] == [digest_of(url) for url in urls]
    assert len(http.json_calls) == 1
    assert len(http.image_calls) == 5  # 3 attempts, then the 2 that were missing


# --------------------------------------------------------------------------- failures


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectTimeout("slow"), "图片检索超时，请稍后重试"),
        (httpx.ConnectError("down"), "无法连接到图片源，请检查网络后重试"),
        (status_error(429), "图片来源限流，请稍后重试"),
        (status_error(500), "图片来源暂时不可用，请稍后重试"),
        (status_error(403), "图片检索失败，请稍后重试"),
        (ValueError("not json"), "图片检索失败，请稍后重试"),
        (
            json.JSONDecodeError("Expecting value", "<html>360图片_访问异常出错</html>", 0),
            "图片源暂时拒绝访问，请稍后重试",
        ),
        (OSError("disk"), "图片检索失败，请稍后重试"),
    ],
)
def test_every_failure_becomes_an_empty_result_with_a_reason(http, settings, error, expected):
    http.json_error = error
    body = outfit_images.search_outfit_images(CATALOG[0], settings=settings)
    assert body["images"] == []
    assert body["error"] == expected
    assert body["provider"] == "so" and body["outfit_id"] == CATALOG[0]["id"]


def test_rate_limited_source_is_retried_once_then_succeeds(http, settings):
    http.json_errors = [status_error(429)]
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    body = outfit_images.search_outfit_images(CATALOG[0], settings=settings)
    assert body["error"] is None and len(body["images"]) == 1
    assert len(http.json_calls) == 2


def test_server_error_retries_once_and_is_negatively_cached(http, settings):
    http.json_error = status_error(500)
    first = outfit_images.search_outfit_images(CATALOG[0], settings=settings)
    assert first["error"] == "图片来源暂时不可用，请稍后重试"
    assert first["cached"] is False
    assert len(http.json_calls) == 2  # the one short backoff retry

    second = outfit_images.search_outfit_images(CATALOG[0], settings=settings)
    assert second["cached"] is True and second["error"] == first["error"]
    assert len(http.json_calls) == 2  # the negative entry absorbs the burst

    third = outfit_images.search_outfit_images(CATALOG[0], refresh=True, settings=settings)
    assert third["cached"] is False
    assert len(http.json_calls) == 4  # refresh deliberately retries the source


def test_client_error_is_not_retried(http, settings):
    http.json_error = status_error(404)
    outfit_images.search_outfit_images(CATALOG[0], settings=settings)
    assert len(http.json_calls) == 1


def test_source_concurrency_is_capped(http, settings):
    state = {"active": 0, "peak": 0}

    def slow(url, params):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.05)
        state["active"] -= 1
        digest = hashlib.sha1(params["q"].encode()).hexdigest()
        return {"list": [so_item(f"https://img.example.com/{digest}.jpg")]}

    http.json_response = slow
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(outfit_images.search_outfit_images, CATALOG[index], settings=settings)
            for index in range(6)
        ]
        assert all(future.result()["error"] is None for future in futures)
    assert state["peak"] <= outfit_images.MAX_IN_FLIGHT
    assert 3 <= outfit_images.MAX_IN_FLIGHT <= 6  # stays inside the polite range


# --------------------------------------------------------------------------- file names


@pytest.mark.parametrize(
    "name",
    [
        "",
        "..",
        "../x.jpg",
        "..\\x.jpg",
        "a/b.jpg",
        "a\\b.jpg",
        "deadbeef",
        "0" * 40 + ".gif",
        "0" * 39 + ".jpg",
        "0" * 40 + ".jpg/../../x.jpg",
    ],
)
def test_file_names_outside_the_whitelist_are_refused(name):
    assert outfit_images.image_file_name(name) is None


def test_cached_image_path_stays_inside_the_cache(settings):
    digest = "a" * 40
    directory = settings.data_dir / "outfit_images" / "img"
    directory.mkdir(parents=True)
    (directory / f"{digest}.jpg").write_bytes(b"jpeg-bytes")

    assert outfit_images.cached_image_path(settings, f"{digest}.jpg") == directory / f"{digest}.jpg"
    assert outfit_images.cached_image_path(settings, f"{digest}.png") is None
    assert outfit_images.cached_image_path(settings, "b" * 40 + ".jpg") is None
    assert outfit_images.cached_image_path(settings, "../studio.sqlite3") is None
    assert outfit_images.content_type_for(f"{digest}.jpg") == "image/jpeg"
    assert outfit_images.content_type_for(f"{digest}.webp") == "image/webp"


# --------------------------------------------------------------------------- HTTP


def test_images_endpoint_returns_the_agreed_contract(http, settings):
    http.json_response = {"list": [so_item("https://img.example.com/a.jpg", title="通勤风衣")]}
    with client_for(settings) as client:
        response = client.get("/api/outfits/soft-tailoring/images?limit=3")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "outfit_id", "query", "provider", "provider_label", "cached", "error", "images",
        }
        assert body["outfit_id"] == "soft-tailoring"
        assert body["query"] == outfit_by_id("soft-tailoring")["image_query"]
        assert body["provider"] == "so" and body["provider_label"] == "360 图片"
        assert body["cached"] is False and body["error"] is None

        image = body["images"][0]
        assert set(image) == {
            "id", "url", "original_url", "source_url", "site", "title",
            "width", "height", "creator", "license",
        }
        assert image["title"] == "通勤风衣" and image["width"] == 800

        served = client.get(image["url"])
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/jpeg"
        assert served.headers["cache-control"] == "public, max-age=604800"
        assert served.content == http.image_response


def test_images_endpoint_404_for_an_unknown_outfit(http, settings):
    with client_for(settings) as client:
        assert client.get("/api/outfits/missing-outfit/images").status_code == 404
    assert http.json_calls == []


def test_images_endpoint_validates_limit_and_page(http, settings):
    with client_for(settings) as client:
        for query in ("limit=0", "limit=13", "limit=abc", "page=-1", "page=10", "page=abc"):
            assert client.get(f"/api/outfits/soft-tailoring/images?{query}").status_code == 422
        assert client.get("/api/outfits/soft-tailoring/images?limit=12&page=9").status_code == 200
    assert len(http.json_calls) == 1


def test_images_endpoint_answers_200_when_the_source_fails(http, settings):
    http.json_error = httpx.ConnectError("down")
    with client_for(settings) as client:
        response = client.get("/api/outfits/soft-tailoring/images")
        assert response.status_code == 200
        body = response.json()
        assert body["images"] == []
        assert body["error"] == "无法连接到图片源，请检查网络后重试"


@pytest.mark.parametrize(
    "name",
    [
        "deadbeef",
        "0" * 40 + ".jpg",
        "0" * 40 + ".gif",
        "..%2Fstudio.sqlite3",
        "a%2Fb.jpg",
        "..%5Cx.jpg",
    ],
)
def test_image_endpoint_refuses_unsafe_or_missing_names(settings, name):
    with client_for(settings) as client:
        assert client.get(f"/api/outfit-images/{name}").status_code == 404


# --------------------------------------------------------------------------- keyed providers


def test_unsplash_provider_follows_the_official_contract(http, settings):
    keyed = variant(settings, image_provider="unsplash", unsplash_access_key="test-key")
    http.json_response = {
        "results": [
            {
                "width": 1200,
                "height": 1600,
                "description": "秋日通勤",
                "urls": {
                    "regular": "https://images.unsplash.com/photo-1",
                    "small": "https://images.unsplash.com/photo-1-small",
                },
                "links": {"html": "https://unsplash.com/photos/1"},
                "user": {"name": "Ada"},
            },
            {"width": 900, "height": 900, "urls": {"regular": "https://images.unsplash.com/2"}},
            {"urls": {}},
            {"width": 100, "height": 100, "urls": {"regular": "https://images.unsplash.com/3"}},
            "not a dict",
        ]
    }
    body = outfit_images.search_outfit_images(CATALOG[0], settings=keyed)

    assert body["provider"] == "unsplash" and body["provider_label"] == "Unsplash"
    call = http.json_calls[0]
    assert call["url"] == UNSPLASH_URL
    assert call["headers"]["Authorization"] == "Client-ID test-key"
    assert call["params"]["page"] == 1 and call["params"]["query"] == CATALOG[0]["image_query"]

    first, second = body["images"]
    assert first["creator"] == "Ada" and first["license"] == "Unsplash License"
    assert first["site"] == "unsplash.com"
    assert first["source_url"] == "https://unsplash.com/photos/1"
    assert first["title"] == "秋日通勤"
    # A photo without a user, a description or detail links still maps cleanly.
    assert second["creator"] is None and second["license"] == "Unsplash License"
    assert second["source_url"] == second["original_url"]
    assert second["title"] == outfit_images.DEFAULT_TITLE


def test_pixabay_provider_follows_the_official_contract(http, settings):
    keyed = variant(settings, image_provider="pixabay", pixabay_api_key="test-key")
    http.json_response = {
        "hits": [
            {
                "imageWidth": 1000,
                "imageHeight": 1500,
                "largeImageURL": "https://cdn.pixabay.com/photo-1.jpg",
                "previewURL": "https://cdn.pixabay.com/photo-1-150.jpg",
                "pageURL": "https://pixabay.com/photos/1",
                "tags": "coat, commute",
                "user": "Lin",
            },
            # No original-sized URL: nothing to localise, so it is dropped.
            {"imageWidth": 800, "imageHeight": 600, "previewURL": "https://cdn/x-150.jpg"},
            "not a dict",
        ]
    }
    body = outfit_images.search_outfit_images(CATALOG[0], settings=keyed)

    assert body["provider"] == "pixabay" and body["provider_label"] == "Pixabay"
    call = http.json_calls[0]
    assert call["url"] == PIXABAY_URL
    assert call["params"]["key"] == "test-key"
    assert call["params"]["image_type"] == "photo"
    assert call["params"]["safesearch"] == "true"
    assert call["params"]["page"] == 1

    assert len(body["images"]) == 1
    image = body["images"][0]
    assert image["creator"] == "Lin" and image["license"] == "Pixabay Content License"
    assert image["original_url"] == "https://cdn.pixabay.com/photo-1.jpg"
    assert image["source_url"] == "https://pixabay.com/photos/1"
    assert image["title"] == "coat, commute"
    assert image["site"] == "pixabay.com"


def test_keyed_provider_without_a_key_falls_back_to_so(http, settings):
    assert outfit_images.resolve_provider(variant(settings, image_provider="pixabay")) == (
        "so",
        "360 图片",
    )
    assert outfit_images.resolve_provider(variant(settings, image_provider="unknown")) == (
        "so",
        "360 图片",
    )
    with_key = variant(settings, image_provider="pixabay", pixabay_api_key="key")
    assert outfit_images.resolve_provider(with_key) == ("pixabay", "Pixabay")

    http.json_response = {"list": [so_item("https://img.example.com/a.jpg")]}
    body = outfit_images.search_outfit_images(
        CATALOG[0], settings=variant(settings, image_provider="unsplash")
    )
    assert body["provider"] == "so" and body["provider_label"] == "360 图片"
    assert http.json_calls[0]["url"] == SO_URL


def test_provider_choice_validation():
    assert outfit_images.validate_provider_choice(" SO ") == "so"
    assert outfit_images.validate_provider_choice("unsplash") == "unsplash"
    for value in ("", "baidu", "360", None):
        with pytest.raises(ValueError):
            outfit_images.validate_provider_choice(value)


# --------------------------------------------------------------------------- settings


def test_settings_and_capabilities_expose_the_image_fields(tmp_path):
    config_path = tmp_path / ".env"
    config_path.write_text("# keep this comment\nITP_DATA_DIR=./data\n", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings, start_worker=False, config_path=config_path)

    with TestClient(app, base_url="http://localhost:8000") as client:
        document = client.get("/api/settings").json()
        assert document["image_provider"] == "so"
        assert document["unsplash_access_key_set"] is False
        assert document["pixabay_api_key_set"] is False
        assert client.get("/api/capabilities").json()["outfit_images"] is True
        assert client.get("/api/capabilities").json()["image_provider"] == "so"

        patched = client.patch("/api/settings", json={"unsplash_access_key": "private-image-key"})
        assert patched.status_code == 200
        assert patched.json()["unsplash_access_key_set"] is True
        assert "private-image-key" not in patched.text
        assert "private-image-key" not in client.get("/api/settings").text
        # The key alone does not change the source: the provider must be selected.
        assert client.get("/api/capabilities").json()["image_provider"] == "so"

        selected = client.patch("/api/settings", json={"image_provider": "unsplash"})
        assert selected.status_code == 200
        assert selected.json()["image_provider"] == "unsplash"
        assert client.get("/api/capabilities").json()["image_provider"] == "unsplash"

        text = config_path.read_text(encoding="utf-8")
        assert text.startswith("# keep this comment")
        assert "ITP_IMAGE_PROVIDER=" in text and "ITP_UNSPLASH_ACCESS_KEY=" in text
        restored = Settings(_env_file=config_path, data_dir=tmp_path / "data")
        assert restored.image_provider == "unsplash"
        assert restored.unsplash_access_key.get_secret_value() == "private-image-key"

        cleared = client.patch("/api/settings", json={"unsplash_access_key": ""})
        assert cleared.json()["unsplash_access_key_set"] is False
        assert client.get("/api/capabilities").json()["image_provider"] == "so"

        pre_existing = client.patch("/api/settings", json={"tencent_model": "3.1"})
        assert pre_existing.status_code == 200
        assert "image_provider" in pre_existing.json()


def test_invalid_image_settings_are_rejected_and_nothing_is_written(tmp_path):
    config_path = tmp_path / ".env"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    app = create_app(settings, start_worker=False, config_path=config_path)

    with TestClient(app, base_url="http://localhost:8000") as client:
        for payload in (
            {"image_provider": "baidu"},
            {"image_provider": ""},
            {"image_provider": 5},
            {"unsplash_access_key": "line\nbreak"},
            {"unsplash_access_key": "x" * 1025},
            {"unsplash_access_key": 7},
            {"unknown_field": 1},
        ):
            assert client.patch("/api/settings", json=payload).status_code == 422
        assert client.get("/api/settings").json()["image_provider"] == "so"
        assert not config_path.exists()
