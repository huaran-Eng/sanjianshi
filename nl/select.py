# -*- coding: utf-8 -*-
"""选题与写作：聚类去重 → 打分 → 按配比选稿 → 逐条写摘要 → 挑战区对照。"""
import difflib
import math
import re
from datetime import datetime

from .llm import parse_json

SYSTEM_WRITER = (
    "你是中文新闻编辑，正在给一位读者写每日早报。铁律：\n"
    "1) 只允许转述【原文】里出现过的事实，不许补充背景、不许推测原因、不许编造数字或引语。\n"
    "2) 原文没写清楚原因或后果的部分，就不写，或写「原文未说明」。\n"
    "3) 语言平实，不用「震惊」「重磅」这类词，不写营销腔。\n"
    "4) 只输出 JSON，不要输出任何解释文字。"
)

SYSTEM_RANK = (
    "你是中文新闻编辑，负责给一位读者挑今天最值得看的条目。读者关注三类：国际局势、AI 发展、"
    "不为人知但值得了解的知识/方法论；明确不喜欢明星八卦。只输出 JSON。"
)


EMOJI_RE = re.compile(
    "[" + "\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U00002190-\U000021FF]]"
)
BOILER = [
    "主作者", "少数派编辑部", "少数派成员", "联合创作", "关注", "本文", "版权", "未经授权",
    "阅读原文", "原文链接", "点击查看", "扫描二维码", "责任编辑", "来源：", "投稿", "邮件联系",
    "免责声明", "转载", "封面图", "扫码", "订阅", "客服", "广告", "作者简介", "已关注",
    "分享到", "微博", "知乎", "微信公众号", "商务合作",
]
ROUNDUP = ("早报", "晚报", "日报", "周报", "周刊", "一周", "今日要闻", "速览", "汇总",
           "盘点", "合集", "weekly", "newsletter", "roundup")
# 读者明确不要的：股票行情、楼市、娱乐八卦、体育比分
NEGATIVE = ("涨停", "跌停", "收盘", "沪指", "纳指", "道琼斯", "股价", "A股", "美股", "港股",
            "基金", "理财", "楼市", "房价", "彩票", "博彩", "星座", "综艺", "八卦", "绯闻",
            "球赛", "比分", "夺冠", "演唱会", "票房", "网红", "带货",
            "期货", "大宗商品", "行情", "合约价", "LME", "金价")


CUT_MARKERS = ("主作者", "联合创作者", "联合创作", "分享到", "点击下方按钮", "举报",
               "首页推荐", "欢迎关注", "关注我们", "本文来自", "投稿邮箱")


def clean_text(text):
    """去掉 RSS 摘要里的作者栏、emoji、重复句和站点样板文字。"""
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    # 去掉行首的栏目标签/作者署名（少数派 Matrix 精选、媒体「文 | xx，作者｜xx」等）
    t = re.sub(r"^(Matrix精选|Matrix|少数派|社区)\s*[^。！？]{0,60}?\d+\s*分钟阅读\s*", "", t)
    t = re.sub(r"^文\s*[|｜]\s*[^，,。]{1,24}[，,]\s*作者\s*[｜|]\s*[^，,。]{1,16}\s*", "", t)
    cut = len(t)
    for mk in CUT_MARKERS:
        i = t.find(mk)
        if i > 30:
            cut = min(cut, i)
    t = t[:cut]
    t = EMOJI_RE.sub(" ", t)
    t = t.replace("\u200b", " ").replace("\ufeff", " ")
    t = re.sub(r"\s+", " ", t).strip()
    parts = re.split(r"(?<=[。！？!?；;])\s*", t)
    keep, seen = [], set()
    for p in parts:
        p = p.strip(" ·|，,、")
        if len(p) < 8:
            continue
        low = p.lower()
        if any(b in low for b in ("主作者", "少数派编辑部", "联合创作")) and len(p) < 90:
            continue
        hits = sum(1 for b in BOILER if b in p)
        if hits >= 2 and len(p) < 90:
            continue
        key = p[:24]
        if key in seen:
            continue
        seen.add(key)
        keep.append(p)
    out = "".join(keep)
    return out.strip()


def looks_garbled(text):
    """判断正文是否编码错乱（欧洲字符/替换符占比高）。"""
    if not text:
        return False
    sample = text[:400]
    bad = sum(1 for ch in sample if "À" <= ch <= "ÿ" or ch == "\ufffd")
    cjk = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
    return bad > 30 and bad > cjk


def is_roundup(title):
    low = (title or "").lower()
    seps = low.count("/") + low.count("｜") + low.count("|") + low.count("／")
    if seps >= 3:
        return True
    return any(k in low for k in ROUNDUP)


def norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", t)
    return t


def cluster_items(items, threshold=0.72):
    """标题相似度聚类：用于去重与「多源确认」。"""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys = [norm_title(i["title"]) for i in items]
    for a in range(n):
        if not keys[a]:
            continue
        for b in range(a + 1, n):
            if not keys[b]:
                continue
            if items[a]["link"] == items[b]["link"]:
                union(a, b)
                continue
            if abs(len(keys[a]) - len(keys[b])) > max(14, len(keys[a]) * 0.7):
                continue
            if difflib.SequenceMatcher(None, keys[a], keys[b]).ratio() >= threshold:
                union(a, b)
    groups = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(idx)
    return [[items[i] for i in idxs] for idxs in groups.values()]


def keyword_score(item, interests):
    text = (item.get("title") or "") + " " + (item.get("summary_text") or "")[:200]
    best_group, best_hits = None, 0
    for gid, conf in interests.items():
        hits = sum(1 for kw in conf.get("keywords", []) if kw and kw.lower() in text.lower())
        if hits > best_hits:
            best_group, best_hits = gid, hits
    group = best_group or (item["groups"][0] if item.get("groups") else None)
    weight = interests.get(group, {}).get("weight", 2) if group else 2
    recency = 0.0
    ts = item.get("ts") or 0
    if ts:
        age_h = max(0.5, (datetime.now().astimezone().timestamp() - ts) / 3600)
        recency = max(0.0, 6.0 - math.log2(age_h + 1) * 2.0)
    kind_bonus = 1.0 if item.get("source_kind") in ("通讯社", "厂商官方", "个人") else 0.0
    title = item.get("title") or ""
    length_penalty = -1.0 if len(title) > 48 else 0.0
    if len(title) > 60:
        length_penalty -= 2.0
    if is_roundup(title):
        length_penalty -= 6.0
    low = text.lower()
    neg = sum(1 for w in NEGATIVE if w.lower() in low)
    neg_penalty = -min(neg * 5.0, 10.0)
    item["neg"] = neg
    item["group"] = group
    item["heuristic"] = round(best_hits * 2.2 + weight + recency + kind_bonus
                              + length_penalty + neg_penalty, 2)
    # 纯消费/行情/八卦且不沾三个方向关键词的，直接不进候选
    if neg and best_hits == 0:
        item["skip"] = True
    return item["heuristic"]


def llm_rank(llm, items, interests, limit=24):
    """让模型给候选打分并标注方向；失败返回 None，走本地启发式。"""
    if not items:
        return None
    lines = []
    for i, it in enumerate(items):
        lines.append("%d) [%s|%s] %s || %s" % (
            i, it.get("source_name"), it.get("source_kind"),
            (it.get("title") or "")[:70], (it.get("summary_text") or "")[:60]))
    head = (
        "候选条目如下（格式：编号) [来源|来源类型] 标题 || 摘要）：\n"
        + "\n".join(lines)
    )
    tail = (
        "\n\n请挑出最值得这位读者看的 " + str(limit) + " 条，给每条 0-100 的重要度分数和方向标签"
        "（world=国际局势 / ai=AI 发展 / know=知识方法论）。\n"
        "要求：三个方向都要有；同一新闻多家报道时挑信息最完整的一条；"
        "不要选娱乐八卦、广告、纯促销。\n"
        "输出 JSON：{\"picks\":[{\"i\":编号,\"score\":分数,\"group\":\"world 或 ai 或 know\","
        "\"reason\":\"为什么选它，15 字内\"}]}"
    )
    prompt = head + tail
    try:
        text = llm.complete([
            {"role": "system", "content": SYSTEM_RANK},
            {"role": "user", "content": prompt},
        ], json_mode=True, max_tokens=2400)
    except Exception:
        return None
    data = parse_json(text)
    if not data or not isinstance(data.get("picks"), list):
        return None
    ranked = []
    for p in data["picks"]:
        try:
            idx = int(p["i"])
            if not (0 <= idx < len(items)):
                continue
            it = items[idx]
            it["llm_score"] = float(p.get("score") or 0)
            it["group_llm"] = p.get("group")
            it["reason_llm"] = (p.get("reason") or "")[:40]
            if p.get("group") in interests:
                it["group"] = p.get("group")
            ranked.append(it)
        except Exception:
            continue
    return ranked or None


def pick_diverse(items, n, used_sources=None, used_links=None):
    """头条用：同一来源不重复，且不选聚合稿。"""
    used_sources = used_sources if used_sources is not None else set()
    used_links = used_links if used_links is not None else set()
    picked = []
    for it in items:
        if len(picked) >= n:
            break
        if it["link"] in used_links or it.get("source_id") in used_sources:
            continue
        if is_roundup(it.get("title") or "") and len(picked) < n:
            continue
        picked.append(it)
        used_sources.add(it.get("source_id"))
        used_links.add(it["link"])
    if len(picked) < n:
        for it in items:
            if len(picked) >= n:
                break
            if it["link"] not in used_links:
                picked.append(it)
                used_links.add(it["link"])
    return picked


def pick_by_quota(items, interests, total, src_cap=2):
    """按方向权重轮转选稿，避免某一方向或某一家媒体独占。"""
    buckets = {}
    for it in items:
        buckets.setdefault(it.get("group") or "other", []).append(it)
    order = sorted(interests.keys(), key=lambda g: -interests[g].get("weight", 1))
    picked, seen, src_used = [], set(), {}
    guard = 0
    while len(picked) < total and guard < total * 10:
        guard += 1
        progressed = False
        for g in order:
            if len(picked) >= total:
                break
            bucket = buckets.get(g) or []
            chosen = None
            for it in bucket:
                if it["id"] in seen:
                    continue
                if src_used.get(it.get("source_id"), 0) >= src_cap:
                    continue
                chosen = it
                break
            if chosen is None:
                continue
            bucket.remove(chosen)
            picked.append(chosen)
            seen.add(chosen["id"])
            sid = chosen.get("source_id")
            src_used[sid] = src_used.get(sid, 0) + 1
            progressed = True
        if not progressed:
            break
    if len(picked) < total:
        for it in items:
            if len(picked) >= total:
                break
            if it["id"] not in seen:
                picked.append(it)
                seen.add(it["id"])
    return picked


def extractive_summary(item, max_sentences=3):
    body = item.get("article_text") or ""
    if looks_garbled(body):
        body = ""
    text = clean_text(body) or clean_text(item.get("summary_text") or "")
    if len(text) < 40:
        return item.get("title") or ""
    parts = re.split(r"(?<=[。！？!?；;])\s*", text)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) < 8:
            continue
        out.append(p)
        if len(out) >= max_sentences:
            break
    return "".join(out)[:220]


def write_one(llm, item, interests):
    """写一条：摘要 + 为什么给你。模型不可用时用摘录（不编造）。"""
    labels = "、".join(interests[g]["label"] for g in interests if g in (item.get("groups") or []))
    body = (item.get("article_text") or item.get("summary_text") or "")[:2500]
    if llm.available() and body:
        user = (
            "读者关注三类：国际局势、AI 发展、不为人知但值得了解的知识/方法论；不喜欢明星八卦。\n"
            "【原文】标题：%s\n来源：%s（%s）\n发布时间：%s\n正文：\n%s\n\n"
            "输出 JSON：{\"summary\":\"2-3 句中文摘要，每句一个事实，只能来自原文\","
            "\"why\":\"一句话说明这条为什么值得这位读者看（也可以写「不相关但重要」）\","
            "\"tags\":[\"最多 3 个短标签\"]}"
        ) % (item.get("title"), item.get("source_name"), item.get("source_kind", ""),
             (item.get("published") or "")[:16], body)
        try:
            text = llm.complete([
                {"role": "system", "content": SYSTEM_WRITER},
                {"role": "user", "content": user},
            ], json_mode=True, max_tokens=500)
            data = parse_json(text) or {}
            summ = (data.get("summary") or "").strip()
            if len(summ) >= 20:
                item["summary"] = summ
                item["why"] = (data.get("why") or "").strip() or "本期为你挑的一条重要内容。"
                item["tags"] = [t for t in (data.get("tags") or []) if isinstance(t, str)][:3]
                item["summary_mode"] = "llm"
                return item
        except Exception:
            pass
    item["summary"] = extractive_summary(item)
    if item.get("reason_llm"):
        item["why"] = "入选理由：" + item["reason_llm"]
    elif labels:
        item["why"] = "属于你关注的「%s」。" % labels
    else:
        item["why"] = "今日值得知道的一条。"
    item["tags"] = []
    item["summary_mode"] = "extractive"
    return item


def write_one_liner(llm, picked, fallback):
    if llm.available() and picked:
        brief = "\n".join("- " + (it.get("title") or "")[:50] for it in picked[:6])
        user = ("以下是今天挑出的头条标题：\n%s\n\n"
                "用一句不超过 40 字的中文概括今天最值得注意的事。只输出 JSON：{\"line\":\"一句话\"}" % brief)
        try:
            text = llm.complete([
                {"role": "system", "content": SYSTEM_WRITER},
                {"role": "user", "content": user},
            ], json_mode=True, max_tokens=120)
            line = ((parse_json(text) or {}).get("line") or "").strip()
            if 8 <= len(line) <= 60:
                return line
        except Exception:
            pass
    return fallback


def compare_pair(llm, left, right):
    """挑战区：同一事件、来源类型不同的两条，生成「两种说法」对照。"""
    if llm.available():
        user = (
            "同一事件的两家报道，来源类型不同，读者想知道它们的分歧在哪。只根据下面两段原文，不许补充。\n"
            "A（%s / %s）：%s\n\nB（%s / %s）：%s\n\n"
            "输出 JSON：{\"question\":\"分歧的核心问题（20 字内）\",\"a\":\"A 强调什么（40 字内）\","
            "\"b\":\"B 强调什么（40 字内）\",\"diff\":\"两者真正不同的地方（30 字内；原文没说的写「原文未说明」）\"}"
        ) % (left.get("source_name"), left.get("source_kind"),
             (left.get("article_text") or left.get("summary_text") or "")[:1200],
             right.get("source_name"), right.get("source_kind"),
             (right.get("article_text") or right.get("summary_text") or "")[:1200])
        try:
            text = llm.complete([
                {"role": "system", "content": SYSTEM_WRITER},
                {"role": "user", "content": user},
            ], json_mode=True, max_tokens=400)
            data = parse_json(text) or {}
            if data.get("a") and data.get("b"):
                return {"question": (data.get("question") or "").strip(),
                        "a": data["a"].strip(), "b": data["b"].strip(),
                        "diff": (data.get("diff") or "").strip(), "mode": "llm"}
        except Exception:
            pass
    return {"question": (left.get("title") or "")[:24],
            "a": extractive_summary(left, 2),
            "b": extractive_summary(right, 2),
            "diff": "两家来源类型不同（%s / %s），原文表述不一致之处需要对照阅读。"
                    % (left.get("source_kind"), right.get("source_kind")),
            "mode": "extractive"}
