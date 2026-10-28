# -*- coding: utf-8 -*-
"""每天跑一次：抓取 -> 聚类 -> 选题 -> 摘要 -> 出静态站（公众号文章版式）。

用法：
  python daily.py                      # 正常出刊（有 key 就 AI 摘要，没有就原文摘录）
  python daily.py --no-llm --no-images # 纯本地演示
  python daily.py --date 2026-10-27 --hours 72 --limit 40
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from nl import report as rep
from nl import select as sel
from nl.article import fetch_article_meta
from nl.fetch import fetch_all, now_local, strip_html
from nl.images import download_image
from nl.llm import LLM
from nl.render import write_site

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def load_yaml(path, key=None):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get(key) or [] if key else data


def dedupe(items):
    seen, out = set(), []
    for it in items:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        out.append(it)
    return out


def build_clusters(items, interests):
    clusters = sel.cluster_items(items)
    reps = []
    for group in clusters:
        if not group:
            continue
        group = sorted(group, key=lambda x: len(x.get("summary_text") or "") + len(x.get("title") or ""), reverse=True)
        rep = dict(group[0])
        rep["source_count"] = len({g["source_id"] for g in group})
        rep["sources"] = [{"name": g["source_name"], "kind": g.get("source_kind"),
                           "link": g["link"]} for g in group[:4]]
        gs = []
        for g in group:
            for gname in (g.get("groups") or []):
                if gname not in gs:
                    gs.append(gname)
        rep["groups"] = gs or rep.get("groups") or []
        rep["_members"] = group
        sel.keyword_score(rep, interests)
        reps.append(rep)
    return reps


def title_overlap(a, b):
    """两条标题共享多少个 2 字词/英文词，用来判断它们是不是真在讲同一件事。"""
    def toks(t):
        t = (t or "").lower()
        out = set(re.findall(r"[a-z]{3,}", t))
        cjk = re.findall(r"[\u4e00-\u9fff]+", t)
        for seg in cjk:
            for i in range(len(seg) - 1):
                out.add(seg[i:i + 2])
        return out
    ta, tb = toks(a), toks(b)
    return len(ta & tb) if ta and tb else 0


def pick_challenge(reps, interests, need=2):
    """挑战区：优先同一事件、来源类型不同的两篇；
    没有同一事件时，只挑「同方向 + 标题确实有共同词」的两条，避免硬凑。"""
    if need < 2:
        return None
    pair = None
    best = -1.0
    for rep in reps:
        members = [m for m in rep.get("_members") or [rep]]
        kinds = {}
        for m in members:
            kinds.setdefault(m.get("source_kind"), m)
        if len(kinds) >= 2:
            ordered = sorted(kinds.values(), key=lambda x: len(x.get("title") or ""), reverse=True)
            a, b = dict(ordered[0]), dict(ordered[1])
            score = rep.get("heuristic", 0) + 2.0
            if score > best:
                best = score
                pair = (a, b, "同一事件")
    if pair:
        return pair
    ordered = [r for r in reps if r.get("group")]
    best_pair, best_overlap = None, 1
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            if a.get("group") != b.get("group"):
                continue
            if not (a.get("source_kind") and b.get("source_kind")):
                continue
            if a["source_kind"] == b["source_kind"]:
                continue
            ov = title_overlap(a.get("title"), b.get("title"))
            if ov > best_overlap:
                best_overlap, best_pair = ov, (dict(a), dict(b), "两个视角")
    if best_pair:
        return best_pair
    return None


def enrich_articles(items, cfg, workers=4):
    timeout = cfg.get("article_timeout", 10)
    chars = cfg.get("article_chars", 2500)
    if not items:
        return

    def one(it):
        meta = fetch_article_meta(it["link"], timeout=timeout, max_chars=chars)
        text = meta.get("text") or ""
        if len(text) > 200:
            it["article_text"] = text
        if not it.get("image_url") and meta.get("image"):
            it["image_url"] = meta["image"]
        if not it.get("title") and meta.get("title"):
            it["title"] = meta["title"]
        return it

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, items))


def attach_images(items, out_dir, cfg, workers=4):
    w = cfg.get("image_max_width", 960)
    q = cfg.get("image_quality", 78)
    img_dir = Path(out_dir) / "assets" / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    def one(it):
        url = it.get("image_url")
        if not url:
            return it
        name = it["id"] + ".jpg"
        if download_image(url, str(img_dir / name), timeout=cfg.get("fetch_timeout", 12), max_width=w, quality=q):
            it["img"] = "assets/img/" + name
        return it

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, items))


def write_summaries(llm, items, interests, workers=4):
    if not items:
        return

    def one(it):
        return sel.write_one(llm, it, interests)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, items))


def load_archives(data_dir, keep=0):
    """读 data/ 下的历史期数；keep=0 表示全部保留（长期归档）。"""
    out = []
    if not Path(data_dir).exists():
        return out
    for p in sorted(Path(data_dir).glob("*.json"), reverse=True):
        if p.name == "index.json":
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                issue = json.load(f)
        except Exception:
            continue
        if issue.get("date"):
            out.append({"date": issue["date"], "weekday": issue.get("weekday"),
                        "one_liner": issue.get("one_liner"), "issue": issue})
        if keep and len(out) >= keep:
            break
    return out


STRIP_ITEM_KEYS = ("article_text", "_members", "summary_html", "summary_text",
                  "sources", "groups", "lang", "neg", "heuristic", "ts")


def slim_item(it, strip_img=False):
    out = {}
    for k, v in it.items():
        if k in STRIP_ITEM_KEYS:
            continue
        if strip_img and k == "img":
            out[k] = ""
            continue
        out[k] = v
    return out


def slim_issue(issue, strip_img=False):
    """数据文件只留展示与归档需要的字段，去掉正文这类大字段（仓库体积可控）。"""
    out = dict(issue)
    for key in ("headline", "featured"):
        out[key] = [slim_item(x, strip_img) for x in issue.get(key) or []]
    if out.get("quick"):
        out["quick"] = [dict(x) for x in out["quick"]]
    ch = issue.get("challenge")
    if ch:
        ch2 = dict(ch)
        if ch2.get("pair"):
            ch2["pair"] = [slim_item(p, strip_img) for p in ch2["pair"]]
        out["challenge"] = ch2
    return out


def backfill():
    """补历史：给 data/ 下已有的期数补分类与总结报告，并精简字段（不联网、不调模型）。"""
    cfg = load_yaml(ROOT / "config.yaml")
    interests = cfg.get("interests") or {}
    data_dir = ROOT / "data"
    if not data_dir.exists():
        print("没有 data/ 目录")
        return 1
    issues = []
    for p in sorted(data_dir.glob("*.json")):
        if p.name == "index.json":
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                issue = json.load(f)
        except Exception as exc:
            print("跳过 %s（%s）" % (p.name, exc))
            continue
        if not issue.get("date"):
            continue
        items = rep.flatten(issue)
        rep.classify(items)
        data = rep.build(None, items, interests, issue.get("stats") or {}, use_llm=False)
        issue["report"] = data
        slim = slim_issue(issue)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=1)
        issues.append(slim)
        print("补齐 %s：%d 条 / 类型 %d 种 / 报告 %s 模式"
              % (issue["date"], len(items), len(data["types"]), data["mode"]))
    index = rep.build_index(issues)
    with open(data_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print("索引已更新：%d 期 / 累计 %d 条 / %s ~ %s"
          % (index["aggregate"]["issues"], index["aggregate"]["items"],
             index["aggregate"]["first"], index["aggregate"]["last"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--date", default="")
    ap.add_argument("--hours", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--sources", default="")
    ap.add_argument("--backfill", action="store_true", help="只补历史数据（分类+报告+精简），不联网")
    args = ap.parse_args(argv)
    if args.backfill:
        return backfill()

    cfg = load_yaml(ROOT / "config.yaml")
    sources = load_yaml(ROOT / "sources.yaml", "sources")
    if args.sources:
        keys = [k.strip() for k in args.sources.split(",") if k.strip()]
        sources = [s for s in sources if any(k in s["id"] for k in keys)]
    interests = cfg.get("interests") or {}
    issue_cfg = cfg.get("issue") or {}
    runtime = cfg.get("runtime") or {}
    counts_cfg = issue_cfg.get("daily_count") or {}
    hours = args.hours or issue_cfg.get("lookback_hours", 48)
    limit = args.limit or issue_cfg.get("max_candidates", 80)
    workers = args.workers or runtime.get("max_workers", 8)

    today = args.date or now_local().strftime("%Y-%m-%d")
    dt = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=now_local().tzinfo)

    print("[1/6] 抓取 %d 个来源 ..." % len(sources), flush=True)
    results = fetch_all(sources, max_workers=workers, timeout=runtime.get("fetch_timeout", 12))
    items, ok, errors = [], 0, []
    for sid, res in results.items():
        if res["error"]:
            errors.append((res["source"]["name"], res["error"]))
        else:
            ok += 1
        items.extend(res["items"])
    raw_total = len(items)
    cutoff = (dt - timedelta(hours=hours)).timestamp()
    fresh, old = [], 0
    for it in items:
        ts = it.get("ts") or 0
        if ts and ts < cutoff:
            old += 1
            continue
        fresh.append(it)
    print("      原始 %d 条，%d 小时内 %d 条（丢弃过期 %d）" % (raw_total, hours, len(fresh), old), flush=True)
    if errors:
        for name, err in errors[:8]:
            print("      - 失败：%s（%s）" % (name, err))

    items = dedupe(fresh)
    reps = build_clusters(items, interests)
    reps = [r for r in reps if not r.get("skip") and not sel.is_roundup(r.get("title") or "")]
    reps.sort(key=lambda x: x.get("heuristic", 0), reverse=True)
    print("[2/6] 去重后 %d 条，聚成 %d 个事件" % (len(items), len(reps)), flush=True)

    llm = LLM(cfg.get("llm") or {})
    if args.no_llm:
        llm.disable()
    if llm.available():
        print("      模型链：%s" % " -> ".join(p["name"] for p in llm.active_providers()), flush=True)
    pool = reps[:limit]
    if llm.available():
        print("[3/6] 模型排序（%d 个候选）..." % len(pool), flush=True)
        ranked = sel.llm_rank(llm, pool, interests, limit=min(40, len(pool)))
        if ranked:
            seen = {id(x) for x in ranked}
            pool = ranked + [x for x in pool if id(x) not in seen]
    else:
        print("[3/6] 未配置模型密钥，使用本地打分（原文摘录模式）", flush=True)

    challenge = pick_challenge(pool, interests, counts_cfg.get("challenge", 2))
    used_links = set()
    if challenge:
        a, b, kind = challenge
        used_links = {a["link"], b["link"]}
    rest = [r for r in pool if r["link"] not in used_links]
    n_head = counts_cfg.get("headline", 3)
    n_feat = counts_cfg.get("featured", 5)
    n_quick = counts_cfg.get("quick", 6)
    used_links = set(used_links)
    headline = sel.pick_diverse(rest, n_head, used_links=used_links)
    rest2 = [r for r in rest if r["link"] not in used_links]
    picked = sel.pick_by_quota(rest2, interests, n_feat + n_quick)
    featured = picked[:n_feat]
    quick = picked[n_feat:n_feat + n_quick]

    print("[4/6] 入选：头条 %d / 精选 %d / 速览 %d / 挑战区 %s"
          % (len(headline), len(featured), len(quick), "有" if challenge else "无"), flush=True)
    to_fetch = list(headline) + list(featured)
    if challenge:
        to_fetch += [challenge[0], challenge[1]]
    enrich_articles(to_fetch, runtime)
    if not args.no_images:
        attach_images(list(headline) + list(featured), args.out, runtime)
    out_dir = Path(args.out)

    write_summaries(llm, list(headline) + list(featured), interests)
    # 速览只有标题、不过模型写摘要，这里单独补一次「英文标题翻中文」
    sel.translate_titles(llm, quick)
    challenge_out = None
    if challenge:
        a, b, kind = challenge
        ch = sel.compare_pair(llm, a, b)
        ch["pair"] = [a, b]
        ch["kind"] = kind
        if kind == "两个视角" and not llm.available():
            ch["question"] = "两条不同的侧重点，放在一起对照看"
            ch["diff"] = ("这两条不是对同一件事的两种说法，而是同一方向下两个不同来源的侧重："
                          "一条来自%s，一条来自%s。放在一起是为了让你看到不同来源关注点的差别。"
                          % (a.get("source_kind"), b.get("source_kind")))
        challenge_out = ch

    def _cut(s, n):
        s = (s or "").strip()
        return s if len(s) <= n else s[:n].rstrip("，、。 ；:：") + "…"

    if len(headline) >= 2:
        def _clean_cut(s, n):
            return _cut(s, n).rstrip("；;，, ").strip()
        titles = [_clean_cut(x["title"], 13) for x in headline[:3]]
        fallback = "今天值得看：" + "；".join(titles)
        while len(fallback) > 46 and len(titles) > 1:
            titles.pop()
            fallback = "今天值得看：" + "；".join(titles)
        if len(titles) == 2:
            titles = [_clean_cut(x["title"], 19) for x in headline[:2]]
            fallback = "今天值得看：" + "；".join(titles)
    elif headline:
        fallback = headline[0]["title"]
    else:
        fallback = "今天没有挑出值得看的条目"
    one_liner = sel.write_one_liner(llm, headline, fallback)
    all_sel = list(headline) + list(featured) + list(quick) + ([challenge[0], challenge[1]] if challenge else [])
    # 分类解析 + 客观总结报告：数字由代码统计，模型只打标签、写归纳
    report = rep.build(llm, all_sel, interests, {
        "scanned": len(fresh), "selected": len(all_sel),
        "sources_ok": ok, "sources_total": len(sources),
    })
    # 挑战区如果是「同一事件，不同来源」，它就属于多源确认，补进报告，
    # 否则会出现「挑战区同一件事两家报」但「多源确认 0 条」的自相矛盾。
    if challenge_out and challenge_out.get("kind") == "同一事件":
        pair = challenge_out.get("pair") or []
        ttl = (pair[0].get("title") if pair else "") or (pair[1].get("title") if len(pair) > 1 else "") or ""
        ttl = ttl.strip()
        conf = list(report.get("confirmed") or [])
        if ttl and all((c.get("title") or "").strip() != ttl for c in conf):
            conf.insert(0, {"title": ttl, "n": len(pair) or 2})
            report["confirmed"] = conf[:6]
            report["confirmed_n"] = len(report["confirmed"])
    counts = {}
    for it in all_sel:
        g = it.get("group") or "other"
        counts[g] = counts.get(g, 0) + 1
    lede_parts = ["%s %d 条" % (interests[g]["label"], counts[g]) for g in interests if counts.get(g)]
    lede = "扫描 %d 条，从 %d/%d 个可用来源里留下 %d 条：%s。" % (
        len(fresh), ok, len(sources), len(all_sel), " · ".join(lede_parts) or "—")
    stats = {
        "scanned": len(fresh), "selected": len(all_sel),
        "raw": raw_total, "clusters": len(reps), "dedup": len(items),
        "sources_ok": ok, "sources_total": len(sources),
        "lookback_hours": hours,
        "llm_mode": "llm" if llm.available() else "extractive",
        "model": llm.provider_label() or llm.model_name(),
        "llm_calls": llm.calls, "cost": round(llm.cost_cny(), 4),
        "generated_at": now_local().strftime("%Y-%m-%d %H:%M"),
        "errors": [{"name": n, "error": e} for n, e in errors],
    }
    all_hist = [a for a in load_archives(ROOT / "data") if a["date"] != today]
    archives = all_hist[:12]
    issue = {
        "date": today,
        "date_cn": "%d 月 %d 日" % (dt.month, dt.day),
        "weekday": WEEKDAYS[dt.weekday()],
        "issue_no": len(all_hist) + 1,
        "one_liner": one_liner,
        "lede": lede,
        "cover_image": (headline[0].get("img") if headline else "") or "",
        "headline": [dict(x) for x in headline],
        "featured": [dict(x) for x in featured],
        "quick": [{"title": x["title"], "title_cn": x.get("title_cn") or "",
                   "link": x["link"], "source_name": x["source_name"],
                   "source_kind": x.get("source_kind"), "id": x["id"],
                   "type": x.get("type"), "type_label": x.get("type_label"),
                   "region": x.get("region"), "region_label": x.get("region_label")} for x in quick],
        "challenge": challenge_out,
        "counts": counts,
        "report": report,
        "stats": stats,
        "archives": [{"date": a["date"], "weekday": a["weekday"]} for a in archives],
    }

    issue_disk = slim_issue(issue)
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    with open(data_dir / (today + ".json"), "w", encoding="utf-8") as f:
        json.dump(issue_disk, f, ensure_ascii=False, indent=1)

    archive_payload = [{"date": today, "weekday": issue["weekday"],
                        "one_liner": issue["one_liner"], "issue": issue_disk}]
    for a in all_hist:
        issue_copy = slim_issue(a["issue"], strip_img=True)
        issue_copy["archives"] = issue["archives"]
        archive_payload.append({"date": a["date"], "weekday": a["weekday"],
                                "one_liner": a["one_liner"], "issue": issue_copy})

    idx_issues = [issue_disk] + [a["issue"] for a in all_hist]
    history = rep.build_index(idx_issues)
    with open(data_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print("[5/6] 写出站点到 %s ..." % args.out, flush=True)
    write_site(issue, args.out, archive_payload, cfg, sources, str(ROOT / "assets"), history)

    print("[6/6] 完成：%s" % (Path(args.out) / "index.html"))
    print("      扫描 %d / 事件 %d / 入选 %d / 来源 %d-%d / 模式 %s / 模型 %s / 成本 ¥%.4f"
          % (stats["scanned"], stats["clusters"], stats["selected"], stats["sources_ok"],
             stats["sources_total"], stats["llm_mode"], stats["model"] or "-", stats["cost"]))
    if llm.errors:
        print("      模型报错 %d 次：%s" % (len(llm.errors), llm.errors[-1][:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
