# -*- coding: utf-8 -*-
"""把一期内容渲染成公众号文章式的静态页面（含 PWA 与归档页）。"""
import hashlib
import html
import json
import os
import shutil
from datetime import datetime

KIND_CLASS = {
    "通讯社": "b-blue", "国际媒体": "b-blue", "厂商官方": "b-gray", "官方": "b-gray",
    "科技媒体": "b-purple", "中文科技": "b-purple", "知识社区": "b-teal",
    "个人": "b-teal", "媒体": "b-gray",
}
GROUP_CLASS = {"world": "world", "ai": "ai", "know": "know"}


def e(s):
    return html.escape(str(s or ""), quote=True)


def hue(seed):
    return int(hashlib.sha1(str(seed).encode("utf-8")).hexdigest()[:4], 16) % 360


def fb_style(seed):
    h = hue(seed)
    return ("background:linear-gradient(135deg,hsl(%d 62%% 58%%),hsl(%d 55%% 38%%))"
            % (h, (h + 48) % 360))


def badge(kind):
    return '<span class="badge %s">%s</span>' % (KIND_CLASS.get(kind, "b-gray"), e(kind or "媒体"))


def item_chips(item):
    """卡片上的分类小标签：事件类型 + 地区。"""
    out = []
    if item.get("type_label"):
        out.append('<span class="chip">%s</span>' % e(item["type_label"]))
    if item.get("region_label"):
        out.append('<span class="chip c-dim">%s</span>' % e(item["region_label"]))
    return "".join(out)


def title_html(item, tag="h3", link=False):
    """标题：有中文译名就显示中文，并把英文原题放在下面（不丢原文，方便核对）。"""
    cn = (item.get("title_cn") or "").strip()
    en = (item.get("title") or "").strip()
    if not cn or cn == en:
        return "<%s>%s</%s>" % (tag, e(en), tag)
    inner = e(cn)
    if link:
        inner = '<a href="%s" target="_blank" rel="noopener" style="text-decoration:none">%s</a>' % (e(item.get("link")), e(cn))
    return "<%s>%s</%s><div class=\"orig-title\">原标题：%s</div>" % (tag, inner, tag, e(en))


def fmt_time(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%m-%d %H:%M")
    except Exception:
        return (iso or "")[:16]


def img_block(item, prefix, cls="thumb"):
    """有本地图用图，没有就用确定性渐变兜底（不占仓库体积）。"""
    src = item.get("img") or ""
    if src:
        src = prefix + src
        return ('<div class="%s"><img src="%s" alt="" loading="lazy" referrerpolicy="no-referrer"></div>'
                % (cls, e(src)))
    name = e(item.get("source_name") or "")
    return ('<div class="%s"><div class="fb" style="%s">%s</div></div>'
            % (cls, fb_style(item.get("id")), name))


def stats_bars(counts):
    total = sum(counts.values()) or 1
    labels = {"world": "国际", "ai": "AI", "know": "知识"}
    rows = []
    for g in ("world", "ai", "know"):
        n = counts.get(g, 0)
        pct = round(n * 100.0 / total)
        rows.append('<div class="bar"><span>%s</span><span class="track"><span class="fill %s" '
                    'style="width:%d%%;display:block"></span></span><em>%d</em></div>'
                    % (labels[g], GROUP_CLASS[g], max(pct, 2), n))
    return '<div class="bars">%s</div>' % "".join(rows)


def cover(issue):
    cover_img = ""
    if issue.get("cover_image"):
        cover_img = '<div class="img" style="background-image:url(%s)"></div>' % e(issue["cover_image"])
    counts = issue.get("counts") or {}
    tags = ['<span>%s %d 条</span>' % (lab, n) for lab, n in
            (("国际", counts.get("world", 0)), ("AI", counts.get("ai", 0)), ("知识", counts.get("know", 0))) if n]
    tags.append('<span>%d 个来源</span>' % issue["stats"].get("sources_ok", 0))
    return ('<div class="cover">%s<div class="inner">'
            '<div class="row"><span class="dot"></span><span>%s</span><span>·</span><span>第 %d 期</span></div>'
            '<div class="date-big">%s</div>'
            '<h1>%s</h1><p class="lede">%s</p>'
            '<div class="tags">%s</div>'
            '</div></div>') % (
        cover_img,
        e(issue.get("weekday") or ""), int(issue.get("issue_no") or 1),
        e(issue.get("date_cn") or ""),
        e(issue.get("one_liner") or ""), e(issue.get("lede") or ""),
        "".join(tags))


def sec_head(tag, title, sub=""):
    return ('<div class="sec"><span class="sec-tag">%s</span><h2>%s</h2>'
            '<div class="sub">%s</div></div>') % (e(tag), e(title), e(sub))


def story(item, idx, prefix):
    src = ('%s<span class="dotsep">·</span>%s<span class="dotsep">·</span>%s'
           % (badge(item.get("source_kind")), e(item.get("source_name")), e(fmt_time(item.get("published")))))
    if item.get("source_count", 1) > 1:
        src += '<span class="dotsep">·</span>%d 家报道' % item["source_count"]
    src += item_chips(item)
    why = ('<div class="why"><b>为什么给你看：</b>%s</div>' % e(item.get("why"))) if item.get("why") else ""
    return ('<div class="story"><div class="num">%02d</div>'
            '%s<div class="meta">%s</div>%s'
            '<p class="sum">%s</p>%s'
            '<a class="read" href="%s" target="_blank" rel="noopener">阅读原文 →</a></div>') % (
        idx, title_html(item, "h3"), src, img_block(item, prefix), e(item.get("summary")), why, e(item.get("link")))


def featured(items, prefix):
    rows = []
    for it in items:
        rows.append('<div class="row">%s<div class="t">%s<p>%s</p>'
                    '<div class="meta">%s<span class="dotsep">·</span>%s%s</div></div></div>' % (
                        img_block(it, prefix, "thumb-sm"), title_html(it, "h4", link=True),
                        e(it.get("summary")), badge(it.get("source_kind")), e(it.get("source_name")),
                        item_chips(it)))
    return '<div class="featured">%s</div>' % "".join(rows)


def challenge_block(ch, prefix):
    if not ch or not ch.get("pair"):
        return ""
    a, b = ch["pair"]
    note = ("同一方向，两个来源的不同侧重" if ch.get("kind") == "两个视角"
            else "同一件事，不同来源可能说法不同")
    return ('<div class="challenge"><div class="meta"><span class="badge b-amber">另一种声音</span>'
            '<span>%s</span></div>' % e(note) +
            '<div class="q">%s</div>'
            '<div class="vs">'
            '<div class="vs-card a"><div class="src">%s%s</div><p>%s</p>'
            '<a href="%s" target="_blank" rel="noopener">看原文 →</a></div>'
            '<div class="vs-card b"><div class="src">%s%s</div><p>%s</p>'
            '<a href="%s" target="_blank" rel="noopener">看原文 →</a></div>'
            '</div>'
            '<div class="diff"><b>分歧点：</b>%s</div></div>') % (
        e(ch.get("question") or "两家怎么说？"),
        badge(a.get("source_kind")), e(a.get("source_name")), e(ch.get("a")), e(a.get("link")),
        badge(b.get("source_kind")), e(b.get("source_name")), e(ch.get("b")), e(b.get("link")),
        e(ch.get("diff")))


def _bar_rows(rows, total):
    total = total or 1
    out = []
    for r in rows:
        pct = max(2, int(round((r.get("n") or 0) * 100.0 / total)))
        out.append('<div class="bar"><span>%s</span><span class="track">'
                   '<span class="fill" style="width:%d%%;display:block"></span></span><em>%d</em></div>'
                   % (e(r.get("label")), pct, r.get("n") or 0))
    return "".join(out)


def report_block(rep):
    """每期客观总结报告：数字全部由代码统计，模型只写归纳（单独标注为判断）。"""
    if not rep:
        return ""
    total = sum((t.get("n") or 0) for t in (rep.get("types") or [])) or 1
    types_html = _bar_rows(rep.get("types") or [], total) or '<div class="rmuted">本期没有类型数据</div>'
    regions_html = _bar_rows(rep.get("regions") or [], total) or '<div class="rmuted">—</div>'
    signals = rep.get("signals") or []
    if signals:
        judge = ('<div class="judge"><b>编辑归纳（判断，不是事实）</b><ul>%s</ul></div>'
                 % "".join("<li>%s</li>" % e(s) for s in signals))
    else:
        judge = ('<div class="judge muted"><b>没有归纳判断</b>：本期未启用模型归纳，'
                 '下面只有统计数字。</div>')
    conf = rep.get("confirmed") or []
    if conf:
        parts = ["%s（%d 家）" % (e((c.get("title") or "")[:34]), c.get("n") or 1) for c in conf]
        conf_html = ('<div class="conf"><b>多源确认 %d 条：</b>%s</div>'
                     % (rep.get("confirmed_n") or len(conf), "；".join(parts)))
    else:
        conf_html = '<div class="conf"><b>多源确认：</b>本期没有多家媒体同时报道的条目。</div>'
    mode = "模型归纳" if rep.get("mode") == "llm" else "规则统计"
    return ('<div class="report">'
            '<div class="rhead"><span class="badge b-teal">%s</span>'
            '<span class="rmeta">数字由程序统计，不经过模型</span></div>'
            '<p class="ov">%s</p>'
            '<div class="rgrid"><div class="rcol"><h5>事件类型</h5>%s</div>'
            '<div class="rcol"><h5>地区</h5>%s</div></div>'
            '%s%s'
            '<div class="rnote">%s</div></div>') % (
        e(mode), e(rep.get("overview") or ""), types_html, regions_html, judge, conf_html,
        e(rep.get("note") or ""))


def quick(items):
    rows = []
    for it in items:
        cn = (it.get("title_cn") or "").strip()
        en = (it.get("title") or "").strip()
        label = cn or en
        extra = ('<span class="q-orig">%s</span>' % e(en)) if (cn and cn != en) else ""
        rows.append('<li><a href="%s" target="_blank" rel="noopener">%s</a>'
                    '<span class="src">%s</span>%s%s</li>' % (
                        e(it.get("link")), e(label), e(it.get("source_name")), item_chips(it), extra))
    return '<div class="quick"><ol>%s</ol></div>' % "".join(rows)


def footer(issue):
    st = issue.get("stats") or {}
    llm_mode = st.get("llm_mode", "extractive")
    model = ("AI 摘要：%s（约 ¥%.3f）" % (st.get("model") or "模型", st.get("cost", 0.0))
             if llm_mode == "llm" else "AI 摘要：本机未配置密钥，本期为「原文摘录」模式（不编造内容）")
    errs = st.get("errors") or []
    if errs:
        names = "、".join("%s（%s）" % (x.get("name"), (x.get("error") or "")[:22]) for x in errs[:6])
        err_note = ('<div class="note errs"><b>本期没抓到的源 %d 个：</b>%s'
                    '%s</div>' % (len(errs), e(names), " 等" if len(errs) > 6 else ""))
    else:
        err_note = ""
    return ('<div class="foot">'
            '<div class="stats">'
            '<div class="stat"><b>%d</b><span>扫描条目</span></div>'
            '<div class="stat"><b>%d</b><span>本期入选</span></div>'
            '<div class="stat"><b>%d/%d</b><span>来源可用</span></div>'
            '<div class="stat"><b>¥%.2f</b><span>本次成本</span></div>'
            '</div>'
            '<div class="note"><b>这一期是怎么来的</b><br>'
            '1）从 %d 个公开 RSS/站点抓取，只保留最近 %s 小时内、能追溯到原文链接的条目；'
            '2）标题聚类去重，同一件事多家报道合成一条并标出「几家报道」；'
            '3）按你的三类关注（国际局势 / AI 发展 / 冷知识方法论）分配名额，避免某方向独占；'
            '4）摘要只转述原文，原文没说的不补；5）挑战区专门放「另一家说法不同」的条目。</div>'
            '<div class="note"><b>防止信息茧房（硬约束）</b>'
            '<ol><li>来源白名单覆盖 %d 个不同站点、多个来源类型；</li>'
            '<li>不按你的点击行为做推荐，每天名额固定；</li>'
            '<li>同一事件尽量给出第二家报道；</li>'
            '<li>每条都带原始链接和时间，摘要可核对；</li>'
            '<li>如果某天你一条都不想点，那就是这个方向不对，告诉我改源。</li></ol></div>'
            '%s'
            '<div class="copy">%s<br>生成时间：%s · 出刊日 %s</div></div>') % (
        st.get("scanned", 0), st.get("selected", 0), st.get("sources_ok", 0), st.get("sources_total", 0),
        st.get("cost", 0.0), st.get("sources_total", 0), st.get("lookback_hours", 48),
        st.get("sources_total", 0), err_note, model, e(st.get("generated_at")), e(issue.get("date")))


def archive_links(issue, is_archive):
    items = issue.get("archives") or []
    if not items:
        return ""
    pre = "../" if is_archive else ""
    links = "".join('<a href="%sarchive/%s.html">%s</a>' % (pre, d["date"], d["date"][5:]) for d in items[:10])
    return '<div class="arch"><b>最近几期：</b>%s<a href="%sarchive.html">全部归档 →</a></div>' % (links, pre)


def page(issue, body, prefix="", is_archive=False):
    title = "%s · %s" % (issue.get("one_liner") or "今日三件事", issue.get("date"))
    return """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta name="theme-color" content="#101820">
<link rel="stylesheet" href="%(pre)sassets/style.css">
<link rel="manifest" href="%(pre)smanifest.json">
<link rel="icon" href="%(pre)sicon.svg" type="image/svg+xml">
<link rel="icon" href="%(pre)sicon-192.png" sizes="192x192" type="image/png">
<link rel="apple-touch-icon" href="%(pre)sapple-touch-icon.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="三件事">
</head><body>
<div class="top"><div class="brand">三件事 · 每日晨读</div>
<nav><a href="%(pre)sindex.html">今天</a><a href="%(pre)sarchive.html">归档</a><a href="%(pre)sabout.html">关于</a></nav></div>
<div class="article">%(body)s%(arch)s</div>
<script>
if ('serviceWorker' in navigator) { window.addEventListener('load', function(){ navigator.serviceWorker.register('%(pre)ssw.js'); }); }
</script>
</body></html>""" % {
        "title": e(title), "desc": e((issue.get("lede") or "")[:120]),
        "pre": prefix, "body": body, "arch": archive_links(issue, is_archive),
    }


def render_issue(issue, prefix=""):
    counts = issue.get("counts") or {}
    parts = [cover(issue)]
    parts.append(sec_head("今日三件事", "值得你花三分钟的三件事",
                          "每个方向至少一条；同一件事多家报道只留一条，标出报道家数"))
    for i, it in enumerate(issue.get("headline") or [], 1):
        parts.append(story(it, i, prefix))
    if issue.get("featured"):
        parts.append(sec_head("继续读", "还有这几条", "没进前三，但值得扫一眼"))
        parts.append(featured(issue["featured"], prefix))
    if issue.get("challenge") and issue["challenge"].get("pair"):
        parts.append(sec_head("挑战区", "另一种声音", "专门放「和你常看的说法不一样」的那一条"))
        parts.append(challenge_block(issue["challenge"], prefix))
    if issue.get("quick"):
        parts.append(sec_head("速览", "一句话过一遍"))
        parts.append(quick(issue["quick"]))
    if issue.get("report"):
        parts.append(sec_head("本期总结", "客观总结报告", "先看数字，再看归纳；归纳单独标注为判断"))
        parts.append(report_block(issue["report"]))
    parts.append(stats_bars(counts))
    parts.append(footer(issue))
    return page(issue, "".join(parts), prefix=prefix)


def render_archive_index(issues, site_name, index=None):
    idx = index or {}
    agg = idx.get("aggregate") or {}
    total_items = int(agg.get("items") or 0)
    if not total_items:
        total_items = sum(int(((it.get("issue") or {}).get("stats") or {}).get("selected") or 0) for it in issues)
    stats = ('<div class="stats arch-stats">'
             '<div class="stat"><b>%d</b><span>累计期数</span></div>'
             '<div class="stat"><b>%d</b><span>累计条目</span></div>'
             '<div class="stat"><b>%s</b><span>起始</span></div>'
             '<div class="stat"><b>%s</b><span>最新一期</span></div></div>') % (
        int(agg.get("issues") or len(issues)), total_items,
        e((agg.get("first") or "—")[5:]), e((agg.get("last") or "—")[5:]))
    cum_html = ""
    if agg.get("types"):
        cum_html = ('<div class="note"><b>累计类型分布（%d 条）</b>%s</div>'
                    % (total_items, _bar_rows(agg["types"], total_items or 1)))
    rows = []
    for it in issues:
        iss = it.get("issue") or {}
        rep = iss.get("report") or {}
        head = (rep.get("overview") or "")[:88]
        chips = "".join('<span class="chip">%s %d</span>' % (e(t.get("label")), t.get("n") or 0)
                        for t in (rep.get("types") or [])[:4])
        rows.append('<div class="row"><div class="t"><h4><a href="archive/%s.html" style="text-decoration:none">'
                    '%s · %s · 第 %d 期</a></h4><p>%s</p>'
                    '<div class="meta">%s<span class="dotsep">·</span>本期 %d 条</div></div></div>'
                    % (it["date"], e(it["date"]), e(it.get("weekday") or ""),
                       int(iss.get("issue_no") or 1), e(head), chips,
                       int((iss.get("stats") or {}).get("selected") or 0)))
    body = (sec_head("归档", "往期", "共 %d 期 · 累计 %d 条；每期都保留分类解析与总结报告"
                     % (len(issues), total_items))
            + stats + cum_html + '<div class="featured">%s</div>' % "".join(rows))
    issue = {"date": "归档", "one_liner": "往期归档", "lede": "", "stats": {}, "archives": []}
    return page(issue, body)


def render_about(config, sources):
    interests = config.get("interests") or {}
    labels = {"world": "国际局势", "ai": "AI 发展", "know": "冷知识与方法论"}
    src_rows = []
    for s in sources:
        groups = "、".join(labels.get(g, g) for g in (s.get("groups") or []))
        src_rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                        % (e(s.get("name")), e(groups), e(s.get("kind")), e("海外" if s.get("overseas") else "国内")))
    body = (sec_head("关于", "这个页面是什么", "自用，每天一期，不是推荐算法")
            + '<div class="note">每天定时从公开源抓取 → 聚类去重 → 按三类关注分名额 → 摘要只转述原文 → '
              '静态页 + 归档。没有任何点击追踪，也没有按偏好做的推荐。</div>'
            + sec_head("来源", "白名单", "共 %d 个来源；国内/海外各一批，海外源在海外机器上抓" % len(sources))
            + '<div class="featured"><table style="width:100%;border-collapse:collapse;font-size:13px">'
              '<tr style="color:#6b7280;text-align:left"><th style="padding:6px 4px">来源</th>'
              '<th style="padding:6px 4px">方向</th><th style="padding:6px 4px">类型</th>'
              '<th style="padding:6px 4px">区域</th></tr>' + "".join(src_rows) + '</table></div>'
            + '<div class="note"><b>分类与总结报告</b><br>每期给每条打「事件类型 / 地区」标签，'
              '并生成一份总结报告：条数、来源、多源确认等数字全部由程序统计，'
              '模型只负责归纳，归纳部分单独标注为「判断」。往期全部保留，归档页可按期回看。</div>'
            + '<div class="note"><b>关于「不编造」</b><br>摘要如果来自模型，会要求只转述原文；'
              '如果原文信息不足，就写「原文未说明」。每条都保留原始链接，欢迎点开核对。</div>')
    issue = {"date": "关于", "one_liner": "关于这个页面", "lede": "", "stats": {}, "archives": []}
    return page(issue, body)


def write_site(issue, out_dir, archive_issues, config, sources, assets_dir, history=None):
    os.makedirs(out_dir, exist_ok=True)
    site_assets = os.path.join(out_dir, "assets")
    os.makedirs(site_assets, exist_ok=True)
    shutil.copyfile(os.path.join(assets_dir, "style.css"), os.path.join(site_assets, "style.css"))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_issue(issue, ""))
    os.makedirs(os.path.join(out_dir, "archive"), exist_ok=True)
    for it in archive_issues:
        other = dict(it["issue"])
        other["archives"] = it.get("archives") or []
        with open(os.path.join(out_dir, "archive", it["date"] + ".html"), "w", encoding="utf-8") as f:
            f.write(render_issue(other, "../"))
    with open(os.path.join(out_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(render_archive_index(archive_issues, config.get("site", {}).get("name", ""), history))
    with open(os.path.join(out_dir, "about.html"), "w", encoding="utf-8") as f:
        f.write(render_about(config, sources))
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": config.get("site", {}).get("name", "三件事"),
            "short_name": "三件事", "start_url": "./index.html", "scope": "./",
            "display": "standalone", "background_color": "#f1f2f4", "theme_color": "#101820",
            "icons": [
                {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"},
                {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        }, f, ensure_ascii=False, indent=1)
    for static_name in ("sw.js", "icon.svg", "icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        shutil.copyfile(os.path.join(assets_dir, static_name), os.path.join(out_dir, static_name))
    return out_dir
    return out_dir