from __future__ import annotations

# 文件职责：集中存放常量、类型定义、进度统计和无网络副作用的通用工具函数。

import datetime as dt
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Literal, NoReturn, Optional, TypedDict

BASE_URL = "http://toogle.club:36024/api"
SESSION_FILE = ".herocraft_session.txt"
LEGACY_SESSION_FILE = ".herocraft_session"
SESSION_FILE_CANDIDATES = (SESSION_FILE, LEGACY_SESSION_FILE)
RESULTS_DIR = "results"
CACHE_DIR = ".herocraft_cache"
DETAIL_CACHE_FILE = "object_details.json"
INVENTORY_CACHE_FILE = "inventory.json"
DEFAULT_BASE_NAMES = {"水", "火", "土", "风"}
DEFAULT_ITEM = "天基量子战争元帅"
DEFAULT_TYPE = "生物"
DEFAULT_MAX_DEPTH = 5
DEFAULT_FORMAT: OutputFormat = "html"
TYPE_LABELS: dict[str, str] = {
    "element": "元素",
    "item": "物品",
    "equipment": "装备",
    "creature": "生物",
    "character": "生物",
    "concept": "概念",
}
TYPE_ALIASES: dict[str, set[str]] = {
    "元素": {"element"},
    "element": {"element"},
    "物品": {"item"},
    "item": {"item"},
    "装备": {"equipment"},
    "equipment": {"equipment"},
    "生物": {"creature", "character"},
    "creature": {"creature", "character"},
    "character": {"creature", "character"},
    "概念": {"concept"},
    "concept": {"concept"},
}


ObjectType = Literal["element", "item", "equipment", "creature", "concept", "character"]
Operation = Literal["add", "subtract"]
OutputFormat = Literal["text", "html"]
BaseDepthCache = dict[tuple[int, int], Optional[int]]


class ApiObject(TypedDict, total=False):
    id: int
    name: str
    emoji: str
    type: ObjectType
    description: str | None
    craft_sources: list["CraftSource"]


class CraftSource(TypedDict):
    operation: Operation
    ingredient_a: ApiObject
    ingredient_b: ApiObject


class ObjectPage(TypedDict):
    items: list[ApiObject]
    total: int
    limit: int
    offset: int

@dataclass
class ProgressStats:
    start_time: float
    detail_requests: int = 0
    cache_hits: int = 0
    nodes_built: int = 0
    recipes_seen: int = 0
    recipes_checked: int = 0
    phase: str = "初始化"
    last_report_time: float = 0.0
    report_interval_seconds: float = 1.0

    def report(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_report_time < self.report_interval_seconds:
            return
        self.last_report_time = now
        elapsed = now - self.start_time
        message = (
            f"\r耗时 {elapsed:6.1f}s | "
            f"请求详情 {self.detail_requests} | "
            f"缓存命中 {self.cache_hits} | "
            f"节点 {self.nodes_built} | "
            f"渲染配方 {self.recipes_seen} | "
            f"筛选配方 {self.recipes_checked} | "
            f"{self.phase}"
        )
        print(message, end="", file=sys.stderr, flush=True)

    def finish(self) -> None:
        self.report(force=True)
        print(file=sys.stderr, flush=True)

def require_id(obj: ApiObject) -> int:
    object_id = obj.get("id")
    if not isinstance(object_id, int):
        raise RuntimeError(f"对象缺少 id：{obj}")
    return object_id


def format_type(obj: ApiObject) -> str:
    raw_type = obj.get("type") or ""
    return TYPE_LABELS.get(raw_type, raw_type or "未知")


def format_object(obj: ApiObject, *, show_id: bool = False, show_type: bool = True) -> str:
    emoji = obj.get("emoji") or ""
    name = obj.get("name") or "未命名"
    object_id = obj.get("id")
    type_label = format_type(obj)
    suffix_parts: list[str] = []
    if show_type:
        suffix_parts.append(type_label)
    suffix = f" · {' · '.join(suffix_parts)}" if suffix_parts else ""
    if show_id:
        id_part = f"#{object_id}"
        return f"{emoji} {name}{suffix}{id_part}".strip()
    return f"{emoji} {name}{suffix}".strip()


def format_type_filter(type_filter: set[str] | None) -> str:
    if not type_filter:
        return ""
    labels = sorted({TYPE_LABELS.get(raw_type, raw_type) for raw_type in type_filter})
    return f"（类型：{'/'.join(labels)}）"


def format_operation(operation: str) -> str:
    if operation == "add":
        return "+"
    if operation == "subtract":
        return "-"
    return operation


def iter_sources(detail: ApiObject) -> Iterable[CraftSource]:
    sources = detail.get("craft_sources", [])
    if not isinstance(sources, list):
        return []
    return sources


def is_base_object(obj: ApiObject, *, base_ids: set[int], base_names: set[str]) -> bool:
    try:
        object_id = require_id(obj)
    except RuntimeError:
        return obj.get("name") in base_names
    return object_id in base_ids or obj.get("name") in base_names

def safe_filename_part(value: str) -> str:
    reserved = '<>:"/\\|?*'
    cleaned = "".join("_" if char in reserved or ord(char) < 32 else char for char in value)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "item"


def default_output_path(target: ApiObject, output_format: OutputFormat) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = safe_filename_part(target.get("name") or "item")
    type_label = safe_filename_part(format_type(target))
    suffix = "html" if output_format == "html" else "txt"
    return os.path.join(RESULTS_DIR, f"{name}-{type_label}_tree-{timestamp}.{suffix}")


def output_path_with_label_before_timestamp(
    output_path: str,
    label: str,
    default_extension: str = "",
    *,
    extension_override: str | None = None,
) -> str:
    stem, extension = os.path.splitext(output_path)
    final_extension = extension_override if extension_override is not None else extension or default_extension
    timestamp_match = re.search(r"-(\d{8}-\d{6})$", stem)
    if timestamp_match is None:
        return f"{stem}{label}{final_extension}"
    return f"{stem[:timestamp_match.start()]}{label}{stem[timestamp_match.start():]}{final_extension}"


def fail(message: str) -> NoReturn:
    print(f"???{message}", file=sys.stderr)
    raise SystemExit(1)


def parse_int_set(raw_value: str) -> set[int]:
    values: set[int] = set()
    for part in raw_value.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise RuntimeError(f"基础元素 id 不是正整数：{part}")
        values.add(int(part))
    return values


def parse_name_set(raw_value: str) -> set[str]:
    return {part.strip() for part in raw_value.split(",") if part.strip()}


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"布尔值只能是 true/false：{value}")


def parse_type_filter(raw_value: str) -> set[str] | None:
    raw_value = raw_value.strip()
    if not raw_value:
        return None
    matched = TYPE_ALIASES.get(raw_value)
    if matched is None:
        choices = "、".join(sorted(TYPE_ALIASES))
        raise RuntimeError(f"未知类型：{raw_value}。可选：{choices}")
    return matched


def is_session_edge_char(char: str) -> bool:
    return char.isspace() or unicodedata.category(char) in {"Cc", "Cf"}


def strip_session_edge_chars(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and is_session_edge_char(value[start]):
        start += 1
    while end > start and is_session_edge_char(value[end - 1]):
        end -= 1
    return value[start:end]


def clean_session_cookie(raw_value: str) -> str:
    value = strip_session_edge_chars(raw_value).strip("'\"")
    value = strip_session_edge_chars(value)
    if value.lower().startswith("cookie:"):
        value = strip_session_edge_chars(value.partition(":")[2])
    for cookie_part in value.split(";"):
        key, separator, cookie_value = strip_session_edge_chars(cookie_part).partition("=")
        if separator and key.strip() == "hc_session":
            value = cookie_value
            break
    if value.startswith("hc_session="):
        value = value.partition("=")[2]
    return strip_session_edge_chars(value).strip("'\"")


def load_session_from_file(path: str = SESSION_FILE) -> str:
    paths = SESSION_FILE_CANDIDATES if path == SESSION_FILE else (path,)
    for session_path in paths:
        if not os.path.exists(session_path):
            continue
        with open(session_path, "r", encoding="utf-8-sig") as file:
            return clean_session_cookie(file.read())
    return ""


def demo_session_cookie_cleaning() -> None:
    assert clean_session_cookie("\ufeff'hc_session=abc='\u202c\u200b") == "abc="
    assert clean_session_cookie("Cookie: other=1; hc_session=abc=; theme=dark\u202c") == "abc="
