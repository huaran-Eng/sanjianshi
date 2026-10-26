# -*- coding: utf-8 -*-
"""配图：下载、压缩、存本地；失败就交给前端用 CSS 渐变封面兜底。"""
import hashlib
import os

import requests
from PIL import Image

from .fetch import HEADERS

Image.MAX_IMAGE_PIXELS = 40_000_000


def download_image(url, dest_path, timeout=10, max_width=960, quality=78):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        if r.status_code != 200:
            return False
        ctype = (r.headers.get("content-type") or "").lower()
        if not ctype.startswith("image"):
            return False
        raw = r.content
        if len(raw) < 2000 or len(raw) > 12 * 1024 * 1024:
            return False
        from io import BytesIO
        img = Image.open(BytesIO(raw))
        img = img.convert("RGB")
        if img.width > max_width:
            h = int(img.height * max_width / img.width)
            img = img.resize((max_width, h), Image.LANCZOS)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        img.save(dest_path, "JPEG", quality=quality, optimize=True)
        return True
    except Exception:
        return False


def cover_hue(seed):
    """内容没有配图时，用标题 hash 决定渐变封面色相，保证同一篇每天颜色一致。"""
    h = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6], 16)
    return h % 360
