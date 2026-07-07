from __future__ import annotations

# 文件职责：封装 HeroCraft HTTP API、本机明文缓存、请求并发闸门和对象解析。

import concurrent.futures
import http.client
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any

from herocraft_core import (
    DETAIL_CACHE_FILE,
    INVENTORY_CACHE_FILE,
    ApiObject,
    ObjectPage,
    ProgressStats,
    format_object,
    format_type_filter,
    require_id,
)

@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    session_cookie: str
    timeout_seconds: float
    max_workers: int
    branch_workers: int
    deep_workers: int
    request_limit: int
    cache_dir: str
    refresh_cache: bool
    refresh_inventory: bool

class HeroCraftClient:
    def __init__(self, config: ClientConfig, progress: ProgressStats | None = None) -> None:
        self._config = config
        self._base_url_parts = urllib.parse.urlparse(config.base_url)
        self._thread_local = threading.local()
        self._detail_cache_lock = threading.RLock()
        self._base_depth_cache_lock = threading.RLock()
        self._cache_save_lock = threading.Lock()
        self._request_semaphore = threading.BoundedSemaphore(config.request_limit)
        self._detail_cache: dict[int, ApiObject] = self._load_detail_cache()
        self._mine_cache: list[ApiObject] | None = self._load_inventory_cache()
        self._details_since_save = 0
        self._progress = progress

    @property
    def max_workers(self) -> int:
        return self._config.max_workers

    @property
    def branch_workers(self) -> int:
        return self._config.branch_workers

    @property
    def deep_workers(self) -> int:
        return self._config.deep_workers

    def _cache_path(self, filename: str) -> str:
        return os.path.join(self._config.cache_dir, filename)

    def _load_detail_cache(self) -> dict[int, ApiObject]:
        if self._config.refresh_cache:
            return {}
        path = self._cache_path(DETAIL_CACHE_FILE)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as file:
                raw_cache = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw_cache, dict):
            return {}
        result: dict[int, ApiObject] = {}
        for raw_id, raw_obj in raw_cache.items():
            if isinstance(raw_id, str) and raw_id.isdigit() and isinstance(raw_obj, dict):
                result[int(raw_id)] = raw_obj
        return result

    def _load_inventory_cache(self) -> list[ApiObject] | None:
        if self._config.refresh_cache or self._config.refresh_inventory:
            return None
        path = self._cache_path(INVENTORY_CACHE_FILE)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                raw_items = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw_items, list):
            return None
        return [item for item in raw_items if isinstance(item, dict)]

    def save_cache(self) -> None:
        with self._cache_save_lock:
            os.makedirs(self._config.cache_dir, exist_ok=True)
            with self._detail_cache_lock:
                detail_cache = {str(object_id): obj for object_id, obj in self._detail_cache.items()}
            with open(self._cache_path(DETAIL_CACHE_FILE), "w", encoding="utf-8") as file:
                json.dump(detail_cache, file, ensure_ascii=False, indent=2)
            if self._mine_cache is not None:
                with open(self._cache_path(INVENTORY_CACHE_FILE), "w", encoding="utf-8") as file:
                    json.dump(self._mine_cache, file, ensure_ascii=False, indent=2)
            self._details_since_save = 0

    def maybe_save_cache(self) -> None:
        if self._details_since_save >= 100:
            self.save_cache()

    def _connection_key(self) -> tuple[str, str, int]:
        scheme = self._base_url_parts.scheme or "http"
        host = self._base_url_parts.hostname
        if host is None:
            raise RuntimeError(f"API 基址缺少 host：{self._config.base_url}")
        port = self._base_url_parts.port or (443 if scheme == "https" else 80)
        return scheme, host, port

    def _thread_connection(self) -> http.client.HTTPConnection:
        scheme, host, port = self._connection_key()
        key = f"{scheme}:{host}:{port}"
        current_key = getattr(self._thread_local, "connection_key", "")
        connection = getattr(self._thread_local, "connection", None)
        if current_key == key and isinstance(connection, http.client.HTTPConnection):
            return connection
        if isinstance(connection, http.client.HTTPConnection):
            connection.close()
        if scheme == "https":
            connection = http.client.HTTPSConnection(host, port, timeout=self._config.timeout_seconds)
        elif scheme == "http":
            connection = http.client.HTTPConnection(host, port, timeout=self._config.timeout_seconds)
        else:
            raise RuntimeError(f"不支持的 API 协议：{scheme}")
        self._thread_local.connection_key = key
        self._thread_local.connection = connection
        return connection

    def _request_json_keep_alive(self, path: str) -> Any:
        base_path = self._base_url_parts.path.rstrip("/")
        full_path = f"{base_path}{path}" if base_path else path
        connection = self._thread_connection()
        headers = {
            "Accept": "application/json",
            "Cookie": f"hc_session={self._config.session_cookie}",
            "Connection": "keep-alive",
        }
        try:
            connection.request("GET", full_path, headers=headers)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
        except (OSError, http.client.HTTPException):
            connection.close()
            self._thread_local.connection = None
            connection = self._thread_connection()
            connection.request("GET", full_path, headers=headers)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status} {path}: {body}")
        return json.loads(body)

    def request_json(self, path: str) -> Any:
        try:
            with self._request_semaphore:
                return self._request_json_keep_alive(path)
        except (OSError, http.client.HTTPException) as exc:
            raise RuntimeError(f"请求失败 {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"返回不是 JSON {path}: {exc}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"请求失败 {path}: {exc.reason}") from exc
        except socket.timeout as exc:
            raise RuntimeError(f"请求超时 {path}") from exc

    def object_detail(self, object_id: int) -> ApiObject:
        with self._detail_cache_lock:
            cached = self._detail_cache.get(object_id)
        if cached is not None:
            if self._progress is not None:
                self._progress.cache_hits += 1
                self._progress.report()
            return cached
        if self._progress is not None:
            self._progress.detail_requests += 1
            self._progress.report()
        detail = self.request_json(f"/objects/{object_id}")
        if not isinstance(detail, dict):
            raise RuntimeError(f"/objects/{object_id} 返回不是对象")
        typed_detail: ApiObject = detail
        with self._detail_cache_lock:
            self._detail_cache[object_id] = typed_detail
            self._details_since_save += 1
        self.maybe_save_cache()
        return typed_detail

    def refresh_object_detail(self, object_id: int) -> ApiObject:
        if self._progress is not None:
            self._progress.detail_requests += 1
            self._progress.report()
        detail = self.request_json(f"/objects/{object_id}")
        if not isinstance(detail, dict):
            raise RuntimeError(f"/objects/{object_id} 返回不是对象")
        typed_detail: ApiObject = detail
        with self._detail_cache_lock:
            self._detail_cache[object_id] = typed_detail
            self._details_since_save += 1
        return typed_detail

    def detail_cache_snapshot(self) -> dict[int, ApiObject]:
        with self._detail_cache_lock:
            return dict(self._detail_cache)

    def my_objects(self) -> list[ApiObject]:
        if self._mine_cache is not None:
            return self._mine_cache

        limit = 500
        def fetch_page(offset: int) -> ObjectPage:
            query = urllib.parse.urlencode({"limit": limit, "offset": offset})
            page = self.request_json(f"/objects/mine?{query}")
            if not isinstance(page, dict):
                raise RuntimeError("/objects/mine 返回不是分页对象")
            return page

        first_page = fetch_page(0)
        total = first_page.get("total", len(first_page.get("items", [])))
        offsets = list(range(limit, total, limit))
        pages: list[ObjectPage] = [first_page]
        if offsets:
            worker_count = min(self._config.max_workers, len(offsets))
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                pages.extend(executor.map(fetch_page, offsets))
        objects: list[ApiObject] = []
        for page in sorted(pages, key=lambda item: item.get("offset", 0)):
            objects.extend(page.get("items", []))
        self._mine_cache = objects
        return objects

    def resolve_object(self, query: str, type_filter: set[str] | None = None) -> ApiObject:
        query = query.strip()
        if not query:
            raise RuntimeError("物品名称或 id 不能为空")
        if query.isdigit():
            obj = self.object_detail(int(query))
            if type_filter and obj.get("type") not in type_filter:
                raise RuntimeError(f"{format_object(obj)} 不符合指定类型")
            return obj

        matches = [obj for obj in self.my_objects() if obj.get("name") == query]
        if type_filter:
            matches = [obj for obj in matches if obj.get("type") in type_filter]
        if not matches:
            fuzzy = [obj for obj in self.my_objects() if query in obj.get("name", "")]
            if type_filter:
                fuzzy = [obj for obj in fuzzy if obj.get("type") in type_filter]
            if fuzzy:
                preview = "，".join(format_object(obj) for obj in fuzzy[:10])
                raise RuntimeError(f"没有精确匹配：{query}{format_type_filter(type_filter)}。相似项：{preview}")
            raise RuntimeError(f"当前账号已发现物品里找不到：{query}{format_type_filter(type_filter)}")
        if len(matches) > 1:
            preview = "，".join(format_object(obj) for obj in matches[:10])
            raise RuntimeError(f"匹配到多个同名物品，请改用 id：{preview}")
        return self.object_detail(require_id(matches[0]))
