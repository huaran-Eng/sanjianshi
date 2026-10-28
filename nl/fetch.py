# -*- coding: utf-8 -*-
"""抓取：把 sources.yaml 里的源拉下来，归一化成统一条目。"""
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
LOCAL_TZ = timezone(timedelta(hours=8))


def now_local():
    return datetime.now(LOCAL_TZ)


def strip_html(html, limit=None):
    if not html:
        return ""
    txt = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    txt = re.sub(r"\s+", " ", txt)
    if limit and len(txt) > limit:
        txt = txt[:limit] + "…"
    return txt


def parse_time(entry):
    """feedparser 的 *_parsed 是 UTC struct_time。拿不到就返回 None。"""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc).astimezone(LOCAL_TZ)
            except Exception:
                continue
    return None


def pick_image(entry, summary_html):
    """从 feed 里找配图：media:content / media:thumbnail / enclosure / 正文第一张图。"""
    cands = []
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key) or []:
            u = (m.get("url") or "").strip()
            if u:
                cands.append(u)
    for enc in entry.get("enclosures") or []:
        u = (enc.get("href") or enc.get("url") or "").strip()
        typ = (enc.get("type") or "").lower()
        if u and (not typ or typ.startswith("image")):
            cands.append(u)
    if summary_html:
        soup = BeautifulSoup(summary_html, "lxml")
        for img in soup.find_all("img"):
            u = (img.get("src") or img.get("data-src") or "").strip()
            if u:
                cands.append(u)
    for u in cands:
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http") and not re.search(r"\.(svg|gif)(\?|$)", u, re.I):
            return u
    return None


def entry_image(entry, summary_html):
    return pick_image(entry, summary_html)


def normalize(src, entry):
    link = (entry.get("link") or "").strip()
    title = strip_html(entry.get("title") or "")
    if not link.startswith("http") or not title:
        return None
    summary_html = ""
    if entry.get("content"):
        summary_html = entry["content"][0].get("value") or ""
    if not summary_html:
        summary_html = entry.get("summary") or ""
    summary_text = strip_html(summary_html, 600)
    published = parse_time(entry)
    iid = hashlib.sha1((link + title).encode("utf-8")).hexdigest()[:16]
    groups = list(src.get("groups") or [])
    return {
        "id": iid,
        "source_id": src["id"],
        "source_name": src["name"],
        "source_kind": src.get("kind", ""),
        "lang": src.get("lang", ""),
        "groups": groups,
        "title": title,
        "link": link,
        "published": published.isoformat() if published else "",
        "ts": published.timestamp() if published else 0,
        "summary_text": summary_text,
        "summary_html": summary_html,
        "image_url": entry_image(entry, summary_html),
        "article_text": "",
    }


def _try_one(url, src, timeout):
    r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    if r.status_code != 200:
        return None, "HTTP %s" % r.status_code
    parsed = feedparser.parse(r.content)
    if not parsed.entries:
        ctype = (r.headers.get("content-type") or "")[:40]
        return None, "解析不到条目（%s）" % (ctype or "empty")
    items = []
    for e in parsed.entries:
        it = normalize(src, e)
        if it:
            items.append(it)
    return (items or None), (None if items else "解析不到条目")


def fetch_source(src, timeout=12):
    """返回 (items, error)。error 为 None 表示成功。
    支持 src["fallbacks"]（备用地址列表）与一次重试：某些源对中国大陆 IP 时好时坏。"""
    urls = [src["url"]] + [u for u in (src.get("fallbacks") or []) if u and u != src["url"]]
    errs = []
    for url in urls:
        for attempt in range(2):
            try:
                items, err = _try_one(url, src, timeout)
                if items:
                    return items, None
                errs.append(err)
                break  # 解析不到条目/HTTP 错误，换下一个地址，不原地重试
            except Exception as exc:
                errs.append("%s" % type(exc).__name__)
                if attempt == 1:
                    break
                continue
    return [], " / ".join([e for e in errs if e][:2]) or "unknown"


def fetch_all(sources, max_workers=8, timeout=12):
    from concurrent.futures import ThreadPoolExecutor
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_source, s, timeout): s for s in sources}
        for fut, src in list(futs.items()):
            items, err = fut.result()
            results[src["id"]] = {"source": src, "items": items, "error": err}
    return results
