"""多数据源 ISBN 查询，支持优先级配置"""
import urllib.request
import json
import re
import ssl
import os

_ctx = None


def _get_ssl_ctx():
    global _ctx
    if _ctx is not None:
        return _ctx
    try:
        _ctx = ssl.create_default_context()
        urllib.request.urlopen("https://www.google.com", timeout=3, context=_ctx)
    except Exception:
        _ctx = ssl.create_default_context()
        _ctx.check_hostname = False
        _ctx.verify_mode = ssl.CERT_NONE
    return _ctx

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "api_config.json")

# ── 所有可用数据源注册表 ──
PROVIDERS = {}


def provider(key, name):
    """装饰器：注册一个数据源"""
    def wrap(fn):
        PROVIDERS[key] = {"name": name, "fn": fn}
        return fn
    return wrap


# ── 工具函数 ──
def _fetch_html(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "BookManager/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_ctx()) as resp:
        return json.loads(resp.read().decode())


# ── 数据源实现 ──

@provider("nlc", "中国国家图书馆")
def _nlc_lookup(isbn):
    url = f"http://opac.nlc.cn/F/?func=find-m&request={isbn}&find_code=ISB&adjacent=Y&local_base=NLC01"
    html = _fetch_html(url)
    tds = re.findall(r'<td[^>]*class=td1[^>]*>(.*?)</td>', html, re.DOTALL)
    items = [re.sub(r"&nbsp;", " ", re.sub(r'<[^>]+>', '', td)).strip() for td in tds if re.sub(r'<[^>]+>', '', td).strip()]

    result = {}
    field_map = {"题名与责任": "raw_title", "出版项": "publisher_raw", "著者": "author", "中图分类号": "clc"}
    for i, item in enumerate(items):
        for key, field in field_map.items():
            if item.strip() == key and i + 1 < len(items):
                result[field] = items[i + 1]

    if not result.get("raw_title"):
        return None

    raw = result["raw_title"]
    title = raw.split("/")[0] if "/" in raw else raw
    title = re.sub(r'\[.*?\]', '', title).strip()
    title = re.sub(r'\s*=\s*.+', '', title).strip()

    publisher = ""
    m = re.search(r':\s*(.+?)(?:,|$)', result.get("publisher_raw", ""))
    if m:
        publisher = m.group(1).strip().rstrip(",").strip()

    author = result.get("author", "")
    author = re.sub(r'\s*(著|编|译|主编|编著|等)$', '', author).strip()

    return {"title": title, "author": author, "publisher": publisher, "clc": result.get("clc", "")}


@provider("google", "Google Books")
def _google_books(isbn):
    data = _fetch_json(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}")
    if not data.get("items"):
        return None
    info = data["items"][0].get("volumeInfo", {})
    return {
        "title": info.get("title", ""),
        "author": ", ".join(info.get("authors", [])),
        "publisher": info.get("publisher", ""),
        "clc": "",
    }


@provider("openlibrary", "Open Library")
def _openlibrary(isbn):
    data = _fetch_json(f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data")
    key = f"ISBN:{isbn}"
    if key not in data:
        return None
    info = data[key]
    return {
        "title": info.get("title", ""),
        "author": ", ".join(a.get("name", "") for a in info.get("authors", [])),
        "publisher": ", ".join(p.get("name", "") for p in info.get("publishers", [])),
        "clc": "",
    }


# ── 配置管理 ──

def _default_config():
    return [{"key": k, "enabled": True} for k in PROVIDERS]


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 确保新增的 provider 也在配置里
            existing = {item["key"] for item in cfg}
            for k in PROVIDERS:
                if k not in existing:
                    cfg.append({"key": k, "enabled": True})
            # 移除已删除的 provider
            cfg = [item for item in cfg if item["key"] in PROVIDERS]
            return cfg
        except Exception:
            pass
    return _default_config()


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── 查询入口 ──

def lookup(isbn):
    """按优先级依次查询，返回第一个成功的结果"""
    cfg = load_config()
    for item in cfg:
        if not item.get("enabled"):
            continue
        p = PROVIDERS.get(item["key"])
        if not p:
            continue
        try:
            result = p["fn"](isbn)
            if result and result.get("title"):
                result["_source"] = p["name"]
                return result
        except Exception:
            continue
    return None
