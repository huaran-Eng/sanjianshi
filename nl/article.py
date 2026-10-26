# -*- coding: utf-8 -*-
"""正文抽取：RSS 只给摘要时，抓原文页把正文拿下来。抓不到就用 feed 摘要。"""
import re

import requests
from bs4 import BeautifulSoup

from .fetch import HEADERS


def extract_text(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside", "form",
                     "iframe", "header", "svg", "video", "figure"]):
        tag.decompose()
    # 优先 article / main
    best = ""
    for sel in ("article", "main"):
        node = soup.find(sel)
        if node:
            t = node.get_text("\n", strip=True)
            if len(t) > len(best):
                best = t
    if len(best) < 200:
        # 退而求其次：找 <p> 最多的 div
        best_div, best_len = None, 0
        for div in soup.find_all("div"):
            ps = div.find_all("p", recursive=False)
            if len(ps) >= 3:
                t = "\n".join(p.get_text(" ", strip=True) for p in ps)
                if len(t) > best_len:
                    best_div, best_len = t, len(t)
        if best_len > len(best):
            best = best_div
    if len(best) < 200:
        best = soup.get_text("\n", strip=True)
    best = re.sub(r"\n{2,}", "\n", best)
    return best.strip()


def decode_body(raw):
    """始终按 UTF-8 / GB18030 试解，不用 requests 猜出来的 Latin-1（中文站会变乱码）。"""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def pick_og_image(soup):
    for prop in ("og:image", "twitter:image", "twitter:image:src"):
        for tag in soup.find_all("meta"):
            key = tag.get("property") or tag.get("name") or ""
            if key.lower() == prop:
                u = (tag.get("content") or "").strip()
                if u.startswith("http"):
                    return u
    link = soup.find("link", rel=lambda v: v and "image_src" in v)
    if link and (link.get("href") or "").startswith("http"):
        return link["href"]
    return ""


def fetch_article_meta(url, timeout=10, max_chars=2500):
    """抓原文：正文 + og:image（feed 没配图时补一张真实配图）。"""
    out = {"text": "", "image": "", "title": ""}
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return out
        if "text/html" not in (r.headers.get("content-type") or ""):
            return out
        page = decode_body(r.content)
        soup = BeautifulSoup(page, "lxml")
        out["image"] = pick_og_image(soup)
        h1 = soup.find("h1") or soup.find("title")
        if h1:
            out["title"] = h1.get_text(" ", strip=True)[:160]
        out["text"] = extract_text(page)[:max_chars]
        return out
    except Exception:
        return out


def fetch_article(url, timeout=10, max_chars=2500):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return ""
        if "text/html" not in (r.headers.get("content-type") or ""):
            return ""
        text = extract_text(decode_body(r.content))
        return text[:max_chars]
    except Exception:
        return ""
