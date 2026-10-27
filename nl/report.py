# -*- coding: utf-8 -*-
"""分类解析 + 每期客观总结报告 + 历史索引。

原则：
1) 条数、来源数、多源确认这些数字全部由代码统计，模型不参与；
2) 模型只做两件事——给每条打「事件类型 / 地区 / 主题」标签、写 2-3 句归纳；
3) 没有模型或模型失败时，标签退回关键词规则，归纳退回纯统计陈述，不编造。
"""
from datetime import datetime

from .llm import parse_json

TYPES = (
    ("policy", "政策监管"),
    ("business", "商业资本"),
    ("product", "产品发布"),
    ("research", "研究进展"),
    ("security", "安全事件"),
    ("world", "国际关系"),
    ("society", "社会民生"),
    ("industry", "行业观察"),
    ("tech", "技术进展"),
    ("other", "其他"),
)
TYPE_LABEL = dict(TYPES)

REGIONS = (
    ("cn", "中国"),
    ("us", "美国"),
    ("eu", "欧洲"),
    ("me", "中东"),
    ("asia", "亚太"),
    ("global", "全球"),
)
REGION_LABEL = dict(REGIONS)

TYPE_RULES = (
    ("policy", ("监管", "法案", "政策", "条例", "合规", "审查", "禁令", "制裁", "关税", "政府",
                "法院", "诉讼", "反垄断", "隐私", "备案", "许可", "处罚", "罚款", "草案", "立法",
                "出口管制", "数据安全", "个人信息", "网信办", "工信部", "国务院", "央行", "证监会",
                "问询", "听证", "征收", "限制令")),
    ("business", ("融资", "并购", "收购", "投资", "估值", "IPO", "上市", "财报", "营收", "亏损",
                  "裁员", "订单", "市值", "分红", "股份", "募资", "领投", "战略投资", "亿元",
                  "千万", "亿美元", "轮融资", "增持", "回购", "拆分", "重组", "合作")),
    ("product", ("发布", "上线", "推出", "开源", "更新", "版本", "新品", "预售", "发售", "内测",
                 "公测", "发布会", "功能", "套件", "客户端", "插件", "公测版", "正式版", "预览版")),
    ("research", ("论文", "研究", "实验", "发现", "突破", "数据集", "基准", "benchmark", "证明",
                  "实验室", "预印本", "理论", "观测", "样本", "测算", "团队在", "学者")),
    ("security", ("漏洞", "攻击", "泄露", "勒索", "黑客", "诈骗", "入侵", "病毒", "木马", "钓鱼",
                  "间谍", "后门", "撞库", "越权", "应急响应")),
    ("world", ("冲突", "停火", "选举", "峰会", "谈判", "外交", "军事", "战争", "会晤", "访问",
               "边境", "大使", "议会", "政变", "军演", "制裁", "领土", "会谈", "协议")),
    ("society", ("事故", "火灾", "地震", "台风", "洪水", "疫情", "医疗", "教育", "就业", "社保",
                 "民生", "天气", "环保", "污染", "食品安全", "交通", "航班", "救援", "补贴")),
    ("industry", ("报告", "调查", "行业", "市场", "趋势", "观察", "复盘", "解读", "分析", "榜单",
                  "白皮书", "统计", "指数", "预测", "展望", "盘点")),
    ("tech", ("模型", "算法", "训练", "推理", "算力", "GPU", "芯片", "大模型", "智能体", "agent",
              "机器人", "自动驾驶", "上下文", "多模态", "架构", "部署", "微调", "蒸馏", "量化",
              "框架", "编程", "代码", "AI", "人工智能", "深度学习", "神经网络")),
)

REGION_RULES = (
    ("cn", ("中国", "国内", "北京", "上海", "深圳", "广州", "浙江", "江苏", "杭州", "成都", "武汉",
            "西安", "南京", "苏州", "合肥", "重庆", "天津", "国务院", "工信部", "央行", "网信办",
            "发改委", "商务部", "证监会", "教育部", "卫健委", "香港", "澳门", "阿里", "腾讯",
            "字节", "华为", "小米", "比亚迪", "宁德", "百度", "京东", "美团", "拼多多", "中芯",
            "大疆", "蔚来", "理想", "小鹏", "寒武纪", "DeepSeek", "深度求索", "月之暗面", "智谱",
            "商汤", "科大讯飞", "中国团队", "国产")),
    ("us", ("美国", "白宫", "美联储", "国会", "硅谷", "加州", "华盛顿", "纽约", "OpenAI", "谷歌",
            "微软", "英伟达", "苹果", "Meta", "亚马逊", "Anthropic", "AMD", "特斯拉", "NASA",
            "哈佛", "斯坦福", "MIT", "高通", "英特尔", "甲骨文", "Salesforce", "马斯克", "奥特曼",
            "美国团队")),
    ("eu", ("欧洲", "欧盟", "德国", "法国", "英国", "伦敦", "巴黎", "柏林", "布鲁塞尔", "荷兰",
            "意大利", "西班牙", "瑞士", "瑞典", "挪威", "丹麦", "芬兰", "爱尔兰", "波兰",
            "欧盟委员会", "欧洲央行")),
    ("me", ("中东", "以色列", "加沙", "伊朗", "沙特", "阿联酋", "黎巴嫩", "叙利亚", "也门",
            "伊拉克", "土耳其", "卡塔尔", "约旦", "埃及", "巴勒斯坦", "哈马斯", "真主党",
            "德黑兰", "特拉维夫", "迪拜")),
    ("asia", ("日本", "韩国", "印度", "东南亚", "越南", "泰国", "新加坡", "印尼", "马来西亚",
              "菲律宾", "朝鲜", "台海", "台湾", "澳大利亚", "新西兰", "首尔", "东京", "孟买",
              "新德里")),
    ("global", ("全球", "国际", "联合国", "世界", "各国", "G20", "世贸", "世界银行", "IMF",
                "北约", "亚太经合")),
)


def _hits(text, kws):
    low = text.lower()
    return sum(1 for k in kws if k and k.lower() in low)


def rules_type(text):
    best, best_n = "other", 0
    for key, kws in TYPE_RULES:
        n = _hits(text, kws)
        if n > best_n:
            best, best_n = key, n
    return best


def rules_region(text):
    best, best_n = "global", 0
    for key, kws in REGION_RULES:
        n = _hits(text, kws)
        if n > best_n:
            best, best_n = key, n
    return best


def apply_rules(item):
    text = (item.get("title") or "") + " " + ((item.get("summary") or item.get("summary_text") or "")[:300])
    if item.get("type") not in TYPE_LABEL:
        item["type"] = rules_type(text)
    if item.get("region") not in REGION_LABEL:
        item["region"] = rules_region(text)
    if not item.get("topic"):
        item["topic"] = (item.get("title") or "")[:28]
    item["type_label"] = TYPE_LABEL.get(item.get("type"), "其他")
    item["region_label"] = REGION_LABEL.get(item.get("region"), "全球")
    return item


def classify(items):
    for it in items or []:
        apply_rules(it)
    return items


SYSTEM = (
    "你是中文新闻编辑，给每天已选出的新闻条目做分类归纳。铁律：\n"
    "1) 分类只能从给定枚举里选，不许自创；\n"
    "2) overview 只允许陈述条目里出现过的事实（标题、摘要里有的），不许补充背景、不许推测影响、"
    "不许出现原文没有的数字；\n"
    "3) signals 是归纳判断，每条 40 字以内，只能基于本期条目，不许引入外部信息；\n"
    "4) 只输出 JSON，不要输出解释。"
)


def _llm_round(llm, items, interests, stats, max_items=24):
    rows = []
    for i, it in enumerate(items[:max_items]):
        rows.append("%d) %s || %s || 来源:%s" % (
            i, (it.get("title") or "")[:80],
            (it.get("summary") or it.get("summary_text") or "")[:120],
            it.get("source_name") or ""))
    types_desc = "、".join(k + "=" + v for k, v in TYPES)
    regions_desc = "、".join(k + "=" + v for k, v in REGIONS)
    head = ("请给下面的每日新闻条目分类，并写本期归纳。\n"
            "事件类型枚举（key=中文）：" + types_desc + "\n"
            "地区枚举（key=中文）：" + regions_desc + "\n"
            "条目（编号) 标题 || 摘要 || 来源）：\n")
    tail = ("\n\n输出 JSON：{\"items\":[{\"i\":编号,\"type\":\"类型key\","
            "\"region\":\"地区key\",\"topic\":\"这条讲什么，6-14 字\"}],"
            "\"overview\":\"本期总览，2-3 句，只陈述事实，不超过 120 字\","
            "\"signals\":[\"归纳判断 1，40 字内\",\"归纳判断 2，最多 3 条\"]}")
    prompt = head + "\n".join(rows) + tail
    text = llm.complete([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ], json_mode=True, max_tokens=1600)
    data = parse_json(text)
    if not isinstance(data, dict):
        return None
    for p in data.get("items") or []:
        try:
            idx = int(p.get("i"))
            if not (0 <= idx < len(items)):
                continue
            it = items[idx]
            if p.get("type") in TYPE_LABEL:
                it["type"] = p["type"]
            if p.get("region") in REGION_LABEL:
                it["region"] = p["region"]
            topic = (p.get("topic") or "").strip()
            if 2 <= len(topic) <= 24:
                it["topic"] = topic
            apply_rules(it)
        except Exception:
            continue
    overview = (data.get("overview") or "").strip()
    signals = [s.strip() for s in (data.get("signals") or []) if isinstance(s, str) and s.strip()][:3]
    if len(overview) < 15 and not signals:
        return None
    return {"overview": overview, "signals": signals}


def _count_by(items, key):
    out = {}
    for it in items:
        k = it.get(key)
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def _rows(counts, pairs):
    rows = [{"key": k, "label": lab, "n": counts.get(k, 0)} for k, lab in pairs if counts.get(k, 0)]
    rows.sort(key=lambda r: -r["n"])
    return rows


def factual_overview(items, interests, stats, groups, types, regions, confirmed):
    n = len(items)
    parts = ["本期入选 " + str(n) + " 条，扫描 " + str(stats.get("scanned", 0)) + " 条原始条目，"
             + str(stats.get("sources_ok", 0)) + "/" + str(stats.get("sources_total", 0)) + " 个来源可用。"]
    gl = []
    for g, conf in (interests or {}).items():
        if groups.get(g):
            gl.append(conf.get("label", g) + " " + str(groups[g]) + " 条")
    if gl:
        parts.append("按方向：" + "、".join(gl) + "。")
    if types:
        tl = [t["label"] + " " + str(t["n"]) + " 条" for t in types[:3]]
        parts.append("按事件类型：" + "、".join(tl) + ("等。" if len(types) > 3 else "。"))
    if regions:
        rl = [r["label"] + " " + str(r["n"]) + " 条" for r in regions[:3]]
        parts.append("按地区：" + "、".join(rl) + ("等。" if len(regions) > 3 else "。"))
    if confirmed:
        parts.append("其中 " + str(len(confirmed)) + " 条有多家媒体同时报道（多源确认），其余为单一来源。")
    else:
        parts.append("本期没有多家媒体同时报道的条目，全部为单一来源。")
    return "".join(parts)


def build(llm, items, interests, stats, use_llm=True):
    items = list(items or [])
    classify(items)
    narrative = None
    if use_llm and llm is not None and items:
        try:
            if llm.available():
                narrative = _llm_round(llm, items, interests, stats)
        except Exception:
            narrative = None
    groups = _count_by(items, "group")
    tcount = _count_by(items, "type")
    rcount = _count_by(items, "region")
    types = _rows(tcount, TYPES)
    regions = _rows(rcount, REGIONS)
    confirmed = []
    for it in items:
        n = int(it.get("source_count") or 1)
        if n >= 2:
            confirmed.append({"title": it.get("title") or "", "n": n})
    confirmed.sort(key=lambda x: -x["n"])
    kinds = {}
    for it in items:
        k = it.get("source_kind") or "媒体"
        kinds[k] = kinds.get(k, 0) + 1
    kind_rows = [{"kind": k, "n": v} for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])]
    overview = (narrative or {}).get("overview") or ""
    if len(overview) < 15:
        overview = factual_overview(items, interests, stats, groups, types, regions, confirmed)
    return {
        "mode": "llm" if (narrative and narrative.get("overview")) else "code",
        "overview": overview,
        "signals": (narrative or {}).get("signals") or [],
        "groups": _rows(groups, tuple((g, c.get("label", g)) for g, c in (interests or {}).items())),
        "types": types,
        "regions": regions,
        "confirmed": confirmed[:6],
        "confirmed_n": len(confirmed),
        "source_kinds": kind_rows,
        "note": ("数字由程序统计；类型/地区标签来自模型或关键词规则；"
                 "「归纳判断」是编辑视角的概括，不是事实，每条都附原文链接可核对。"),
    }


def flatten(issue):
    out = []
    for key in ("headline", "featured", "quick"):
        for it in issue.get(key) or []:
            out.append(it)
    ch = issue.get("challenge") or {}
    for it in ch.get("pair") or []:
        out.append(it)
    return out


def index_row(issue):
    rep = issue.get("report") or {}
    st = issue.get("stats") or {}
    return {
        "date": issue.get("date") or "",
        "weekday": issue.get("weekday") or "",
        "issue_no": issue.get("issue_no") or 1,
        "one_liner": issue.get("one_liner") or "",
        "selected": st.get("selected") or 0,
        "sources_ok": st.get("sources_ok") or 0,
        "groups": issue.get("counts") or {},
        "types": {t["key"]: t["n"] for t in rep.get("types") or []},
        "regions": {r["key"]: r["n"] for r in rep.get("regions") or []},
        "head": (rep.get("overview") or "")[:70],
    }


def aggregate(rows):
    tsum, rsum = {}, {}
    for r in rows:
        for k, n in (r.get("types") or {}).items():
            tsum[k] = tsum.get(k, 0) + n
        for k, n in (r.get("regions") or {}).items():
            rsum[k] = rsum.get(k, 0) + n
    dates = sorted([r["date"] for r in rows if r.get("date")])
    return {
        "issues": len(rows),
        "items": sum(int(r.get("selected") or 0) for r in rows),
        "first": dates[0] if dates else "",
        "last": dates[-1] if dates else "",
        "types": _rows(tsum, TYPES),
        "regions": _rows(rsum, REGIONS),
    }


def build_index(issues):
    rows = [index_row(i) for i in issues or [] if i.get("date")]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {
        "updated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "issues": rows,
        "aggregate": aggregate(rows),
    }
