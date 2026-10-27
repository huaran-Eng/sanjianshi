# 三件事 · 每日晨读

自用的每日一页新闻：每天定时抓公开源头 → 聚类去重 → 按你的三类关注分名额 → 输出一页「公众号文章式」图文 → 手机上添加到桌面当 App 用。

- 三个方向：**国际局势 / AI 发展 / 不为人知的知识**
- 两个区：**今日三件事**（大字卡）+ **另一种声音**（对照区）
- 反茧房硬约束：来源白名单 ≥5 个站点、每天名额固定、不做点击推荐、每条带原始链接
- 每条带 **事件类型 / 地区** 分类标签；每期末尾有一份 **客观总结报告**（数字程序统计，归纳单独标注）
- **历史长期留存**：每期精简后的 JSON 进仓库，归档页可按期回看 + 看累计分布
- 没配模型 key 也能跑：走「原文摘录」模式，不编造内容

---

## 一、本地先跑起来（Windows，2 分钟）

```
cd E:\DeepSeek work\每日新闻
"C:\Program Files\Python313\python.exe" -m pip install -r requirements.txt
"C:\Program Files\Python313\python.exe" daily.py --out site
"C:\Program Files\Python313\python.exe" -m http.server 8200 -d site
```

浏览器打开 http://127.0.0.1:8200/ ，看到当天一期。

常用参数：

```
python daily.py --out site                  # 正常出刊（全部源）
python daily.py --sources qbitai,sspai      # 只跑指定源，调试用
python daily.py --no-images                 # 不下载图片（省流量）
python daily.py --no-llm                    # 强制摘录模式
python daily.py --date 2026-10-26           # 指定期号日期
python daily.py --backfill                  # 只补历史：给 data/ 里旧期加分类+报告并重建索引（不联网）
```

> 本机在国内，海外源（BBC/NYT/Verge 等）会超时，属正常；线上跑在 GitHub Actions（海外 IP），全部源都能抓。

---

## 二、部署到手机（约 10 分钟，0 元）

前置：GitHub 账号 `huaran-Eng`。仓库必须是**公开**仓库，否则 Pages 也要额外授权。

1. 新建仓库：名字建议 `sanjianshi`，Public，**不要**勾选 README。
2. 把本目录全部文件上传上去（`site/` 和 `_test_site/` 不用传，`.github/` 要传）。
   网页上传：仓库页 → Add file → Upload files → 拖文件夹进去 → Commit。
3. 仓库 Settings → **Pages** → Source 选 **GitHub Actions**（不要选 branch）。
4. 仓库 Settings → Secrets and variables → Actions → New repository secret：
   - Name：`DEEPSEEK_API_KEY`
   - Value：你的 DeepSeek key（在 https://platform.deepseek.com 充值 20 元后创建，只存进 GitHub，不要发给我或贴聊天里）
   不填也能跑，只是摘要变成原文摘录。
5. 仓库顶部 **Actions** → 左侧「每日出刊」→ Run workflow，手动跑一次（约 2-4 分钟）。
6. 跑完绿勾后访问：`https://huaran-eng.github.io/sanjianshi/`
   首次部署 Pages 生效需要 1-2 分钟。
7. 手机 Chrome/Edge 打开这个地址 → 菜单 → **添加到主屏幕**，之后从桌面图标打开，和 App 一样。

以后每天北京时间 **05:30** 自动出刊（`cron: 30 21 * * *` UTC）。想改时间就改 `.github/workflows/daily.yml` 里那一行（UTC = 北京时间 - 8）。

---

## 三、分类解析 · 总结报告 · 历史留存

每期比第一版多三样东西：

**1. 分类标签**——每条新闻标两个维度：

- 事件类型：政策监管 / 商业资本 / 产品发布 / 研究进展 / 安全事件 / 国际关系 / 社会民生 / 行业观察 / 技术进展 / 其他
- 地区：中国 / 美国 / 欧洲 / 中东 / 亚太 / 全球

有模型 key 时由模型打标（只能从上面枚举里选，不许自创）；没有 key 时用关键词规则兜底，不会出现「没标签」。

**2. 客观总结报告**——每期最后一块「本期总结」：

| 部分 | 谁生成的 | 说明 |
|---|---|---|
| 本期条数、类型分布、地区分布、多源确认条数 | 程序统计 | 数字不经过模型，可复算 |
| 「编辑归纳（判断，不是事实）」1–3 条 | 模型 | 单独标注；没 key 时显示「没有归纳判断」，不编造 |

**3. 历史留存**——

- `data/YYYY-MM-DD.json`：每期一份，已精简（去掉正文全文、成员列表等大字段，仓库不会膨胀）
- `data/index.json`：累计索引（期数、条目、类型/地区累计分布）
- `archive.html` 归档页：累计期数 / 累计条目 / 起止日期 / 累计类型分布 + 每期一行（总览前 88 字 + 类型 chips + 本期条数）
- 补旧数据：`python daily.py --backfill`（不联网、不调模型，纯规则补分类 + 报告 + 精简 + 重建索引）

---
## 四、日常怎么改（都是改配置文件，不用改代码）

| 想改什么 | 改哪里 |
|---|---|
| 三个方向的关键词、权重 | `config.yaml` → `interests` |
| 每期条数（头条/精选/速览/挑战区） | `config.yaml` → `issue.daily_count` |
| 时间窗口、候选上限 | `config.yaml` → `lookback_hours` / `max_candidates` |
| 源白名单（加源、删源） | `sources.yaml` |
| 出刊时间 | `.github/workflows/daily.yml` 的 `cron` |
| 换模型（DeepSeek/通义/智谱都可以） | `config.yaml` → `llm.base_url` / `model` / `price_*` |

改完提交，手动跑一次 Actions 就能看到效果。

---

## 五、成本与坑

- **成本**：一天约 5 千字进、4 百字出，按 DeepSeek 空闲价算 ≈ **¥2/月**；20 元额度能跑半年以上。用满模型配额也只 ¥6/月量级。
- **免费额度**：GitHub Actions 私有仓库 2000 分钟/月，本仓库公开仓库不计费。
- **Actions 会自动停**：仓库连续 60 天无提交活动，定时任务会被 GitHub 停用；去 Actions 页点一次 Run workflow 就恢复（也可以顺手改一行文件提交一次）。
- **海外源在本机抓不到**：国内网络访问 BBC/NYT/Verge 等会超时。线上 Actions 是海外机房，没问题。
- **公众号不能自动抓**：微信公众号没有官方文章接口，第三方抓取靠代理池，随时失效且灰色。第一版不做。
- **图片**：文章图只进本期产物，不进仓库（仓库不会变大）；归档页里没图的条目用渐变色块占位。
- **摘录 ≠ 事实核查**：每条都带原文链接，数字以原文为准。

---

## 六、文件结构

```
daily.py            主流程：抓取 → 聚类 → 选题 → 摘要 → 渲染 → 写站
config.yaml         站点信息 / 三个方向 / 条数 / 模型 / 运行参数
sources.yaml        24 个源白名单（中文 9 + 英文 15）
requirements.txt    Python 依赖
nl/fetch.py         RSS 抓取、时间解析、配图提取
nl/article.py       抓原文正文 + og:image，处理编码
nl/images.py        下载图片、压到 960px、存 JPEG
nl/select.py        聚类去重、打分、选稿、摘要、挑战区对照
nl/report.py        分类打标（类型/地区）+ 客观总结报告 + 累计索引
nl/llm.py           OpenAI 兼容接口（DeepSeek/通义/智谱通用）
nl/render.py        公众号文章式 HTML + PWA + 归档页
assets/style.css    版式
assets/sw.js        Service Worker（离线可看上一期）
assets/icon.svg     桌面图标
.github/workflows/daily.yml  每天 05:30 自动出刊并发布 Pages
data/               每天一期 JSON + index.json 累计索引（精简后提交进仓库，用于归档和期号）
site/               构建产物（不提交，由 Actions 生成并发布）
需求澄清.md / 设计确认.md   需求和方案记录
```

---

## 七、下一步（还没做的）

1. **公众号手动入库**：微信里看到好文 → 分享链接 → 粘贴到一个页面 → 进当天候选（第二版）。
2. **周末深度版**：周日出一期「这一周」长文（同一套数据，换版式）。
3. **反馈按钮**：每条下方「有用/没用」两个按钮，只在本地记录，用来每月人工审计源质量（不做算法推荐）。

