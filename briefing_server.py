#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多传感器融合导航每日简报 —— 独立脚本
部署：放到常开服务器，cron 每天定时运行即可。
功能：arXiv 抓论文 + 行业资讯 + (可选)LLM 中文提炼 + 推企业微信群机器人。
依赖：仅 Python3 标准库，无需 pip install。

密钥一律走环境变量或同目录 .llm.env（不要提交到 git）：
  WECOM_WEBHOOK   企业微信群机器人 webhook 完整 URL
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL   可选，OpenAI 兼容接口
"""
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
import json, datetime, re, os, gzip, sys, time, html

_HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_HERE, "briefing_state.json")
LOG_FILE = os.path.join(_HERE, "briefing.log")
LLM_ENV_FILE = os.path.join(_HERE, ".llm.env")
BJT = datetime.timezone(datetime.timedelta(hours=8))


def _load_llm_env_file():
    """读取 .llm.env；已有环境变量优先，不覆盖。"""
    try:
        with open(LLM_ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_llm_env_file()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
WEBHOOK = (os.environ.get("WECOM_WEBHOOK") or os.environ.get("WEBHOOK") or "").strip()

# 合并为单次查询（一次请求拿全部，大幅降低 arXiv 限流(429)概率）
ARXIV_QUERY = (
    '(all:"sensor fusion" AND (all:localization OR all:navigation OR all:SLAM OR all:odometry)) OR '
    '(all:"LiDAR-IMU" OR all:"visual-inertial" OR all:"GNSS/INS" OR all:"multi-modal fusion") OR '
    '(all:"multi-sensor" AND (all:SLAM OR all:navigation OR all:localization)) OR '
    '(all:"radar" AND all:"camera" AND (all:fusion OR all:perception)) OR '
    '(all:"sensor fusion" AND (all:robot OR all:autonomous))'
)
PAPER_LIMIT = 5          # 每天推送论文篇数
PAPER_LOOKBACK_DAYS = 90 # 论文池窗口：不要求「今天新发」，从未推过的里取
PAPER_ID_KEEP = 240      # 已推 arXiv id 最多保留条数（约够轮换数月）
NEWS_LIMIT = 8  # 简报资讯条数；按类别轮询入选，避免被技术帖占满
# Bing/Google 检索词：偏行业与公司，不再只盯传感器融合
NEWS_QUERIES = [
    "自动驾驶 行业",
    "智能驾驶 量产",
    "Robotaxi 自动驾驶",
    "autonomous driving industry",
]
# 自定义 RSS 源（可选）：把你能访问的国内科技/汽车媒体 RSS 填进来，例如
#   "https://www.qbitai.com/feed",   # 量子位
#   "https://www.cheddongxi.com/feed",
# 留空则仅用 Bing/Google News 检索。境内服务器建议至少加 1-2 个国内源。
NEWS_RSS_FEEDS = []
# 微信公众号：行业 / 智驾公司 / 技术 三类；抓取后按组轮询，保证简报有行业面
WEIXIN_QUERY_GROUPS = [
    ("industry", [
        "自动驾驶",
        "智能驾驶",
        "Robotaxi",
        "智驾 量产",
        "高阶智驾",
    ]),
    ("company", [
        "华为智驾",
        "特斯拉 FSD",
        "小鹏 智驾",
        "理想 智驾",
        "蔚来 智驾",
        "百度 Apollo",
        "小马智行",
        "文远知行",
    ]),
    ("tech", [
        "多传感器融合",
        "SLAM",
        "组合导航",
    ]),
]
CORE = ["localization", "navigation", "slam", "odometry", "mapping",
        "visual-inertial", "vio", "lidar-imu", "gnss", " ins "]
FUS = ["fusion", "multi-modal", "multimodal", "multi-sensor", "multisensor",
       "visual-inertial", "lidar-imu", "gnss/ins",
       "lidar", "imu", "radar", "camera", "gnss", "sensor"]
# 明显离题领域，命中即排除（避免动作识别/图像修复/行人重识别/光学设计等混入）
BLOCK = ["action recognition", "action localization", "temporal localization",
         "person re-identification", "image inpainting", "sketch",
         "nanophotonic", "color router", "inverse design",
         "histopath", "medical imaging"]


def now_bjt():
    return datetime.datetime.now(BJT)


def log(msg):
    line = "[%s] %s" % (now_bjt().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pushed_paper_ids": [], "news_titles": [], "last_run": ""}


def save_state(s):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("save state failed: %s" % e)


def fetch_arxiv(since_date):
    papers = {}
    url = ("http://export.arxiv.org/api/query?search_query=%s"
           "&sortBy=submittedDate&sortOrder=descending&max_results=200"
           % urllib.parse.quote(ARXIV_QUERY))
    data = None
    for attempt in range(3):
        try:
            data = http_get(url)
            break
        except Exception as e:
            log("arxiv query failed (attempt %d): %s" % (attempt + 1, e))
            time.sleep(5)
    if not data:
        log("arxiv 全部请求失败，本次跳过论文")
        return papers
    for m in re.finditer(r"<entry>(.*?)</entry>", data, re.S):
            e = m.group(1)
            aid = re.search(r"<id>(.*?)</id>", e)
            if not aid or "/abs/" not in aid.group(1):
                continue
            aid = aid.group(1).strip()
            arxiv_id = aid.split("/abs/")[-1]
            published = re.search(r"<published>(.*?)</published>", e).group(1)[:10]
            try:
                pdate = datetime.date.fromisoformat(published)
            except Exception:
                continue
            if pdate < since_date:
                continue
            title = re.search(r"<title>(.*?)</title>", e, re.S).group(1).replace("\n", " ").strip()
            summary = re.search(r"<summary>(.*?)</summary>", e, re.S).group(1).replace("\n", " ").strip()
            authors = re.findall(r"<name>(.*?)</name>", e)
            authors = ", ".join(authors[:3]) + (" 等" if len(authors) > 3 else "")
            t = (title + " " + summary).lower()
            if any(b in t for b in BLOCK):
                continue
            if sum(k in t for k in CORE) >= 1 and sum(k in t for k in FUS) >= 1:
                if arxiv_id not in papers:
                    papers[arxiv_id] = {"arxiv_id": arxiv_id, "title": title,
                                        "published": published, "summary": summary,
                                        "authors": authors, "url": aid}
    return papers


def pick_papers(arxiv_all, pushed_ids, k=PAPER_LIMIT):
    """每天固定推 k 篇：优先近窗口内从未推过的（新→旧）；不够则从最早推过的开始轮换。"""
    pushed_ids = list(pushed_ids or [])
    pushed_set = set(pushed_ids)
    unseen = [p for aid, p in arxiv_all.items() if aid not in pushed_set]
    unseen.sort(key=lambda p: p["published"], reverse=True)
    picked = unseen[:k]
    n_fresh = len(picked)
    if len(picked) < k:
        picked_ids = set(p["arxiv_id"] for p in picked)
        for aid in pushed_ids:  # 列表头部 = 更早推过，先轮换回来
            if len(picked) >= k:
                break
            p = arxiv_all.get(aid)
            if p and aid not in picked_ids:
                picked.append(p)
                picked_ids.add(aid)
    n_recycle = len(picked) - n_fresh
    log("papers pick: fresh=%d recycle=%d pool=%d pushed=%d" % (
        n_fresh, n_recycle, len(arxiv_all), len(pushed_ids)))
    return picked


def update_pushed_ids(pushed_ids, picked):
    """今日已推的 id 移到队尾；超出 PAPER_ID_KEEP 则丢掉最旧的。"""
    today_ids = [p["arxiv_id"] for p in picked]
    today_set = set(today_ids)
    rest = [i for i in (pushed_ids or []) if i not in today_set]
    return (rest + today_ids)[-PAPER_ID_KEEP:]


def _parse_rss_items(data):
    """从 RSS xml 文本解析出 (title, link, pub) 列表，解析失败返回 []。"""
    out = []
    try:
        root = ET.fromstring(data)
    except Exception as e:
        log("rss parse failed: %s" % e)
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if title and link:
            out.append({"title": title, "link": link, "pub": pub})
    return out


def fetch_news_weixin():
    """搜狗微信搜索(type=2 文章)：按关键词实时抓最新公众号文章 + 摘要。境内最稳的资讯源。"""
    items, seen = [], set()
    for group, queries in WEIXIN_QUERY_GROUPS:
        for q in queries:
            url = "https://weixin.sogou.com/weixin?type=2&query=%s&ie=utf8" % urllib.parse.quote(q)
            try:
                data = http_get(url)
            except Exception as e:
                log("weixin search failed (%s): %s" % (q, e))
                continue
            # 按结果块(txt-box)切分，块内抓「标题链接 + 文章摘要」，避免错位
            for b in data.split('<div class="txt-box">')[1:]:
                links = re.findall(r'<a[^>]*href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>', b, re.S)
                mlink = None
                for href, t in links:
                    if html.unescape(re.sub(r"<[^>]+>", "", t)).strip():  # 跳过图片空链接
                        mlink = (href, t)
                        break
                if not mlink:
                    continue
                title = html.unescape(re.sub(r"<[^>]+>", "", mlink[1])).strip()
                if not title or title in seen:
                    continue
                msum = re.search(r'<p class="txt-info"[^>]*>(.*?)</p>', b, re.S)
                summary = ""
                if msum:
                    summary = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", msum.group(1))).strip())[:60]
                seen.add(title)
                items.append({"title": title,
                              "link": "https://weixin.sogou.com" + mlink[0].replace("&amp;", "&"),
                              "pub": "", "summary": summary, "group": group})
            time.sleep(1.2)
    return items


def _tag_group(items, group):
    for n in items:
        n.setdefault("group", group)
    return items


def fetch_news_bing():
    items = []
    for q in NEWS_QUERIES:
        url = "https://www.bing.com/news/search?q=%s&format=rss&setlang=zh-CN" % urllib.parse.quote(q)
        try:
            items += _tag_group(_parse_rss_items(http_get(url)), "industry")
        except Exception as e:
            log("bing news failed: %s" % e)
    return items


def fetch_news_google():
    items = []
    for q in NEWS_QUERIES:
        url = "https://news.google.com/rss/search?q=%s&hl=zh-CN&gl=CN&ceid=CN:zh-Hans" % urllib.parse.quote(q)
        try:
            items += _tag_group(_parse_rss_items(http_get(url)), "industry")
        except Exception as e:
            log("google news failed: %s" % e)
    return items


def fetch_news_feeds():
    items = []
    for url in NEWS_RSS_FEEDS:
        try:
            items += _tag_group(_parse_rss_items(http_get(url)), "industry")
        except Exception as e:
            log("feed failed: %s" % e)
    return items


def fetch_news():
    """多源容错：微信(搜狗)优先；够用则跳过境内常超时的 Bing/Google。"""
    items, seen = [], set()

    def _merge(src):
        for n in src:
            if n["title"] in seen:
                continue
            seen.add(n["title"])
            items.append(n)

    _merge(fetch_news_weixin())
    _merge(fetch_news_feeds())
    if len(items) < NEWS_LIMIT * 2:
        _merge(fetch_news_bing())
        _merge(fetch_news_google())
    else:
        log("微信资讯已够用(%d)，跳过 Bing/Google" % len(items))
    if not items:
        log("所有新闻源均不可用，本次跳过资讯")
    return items


def pick_diverse_news(items, k=NEWS_LIMIT):
    """按 industry / company / tech 轮询取条，避免简报被同一类技术帖占满。"""
    buckets, order = {}, []
    for n in items:
        g = n.get("group") or "other"
        if g not in buckets:
            buckets[g] = []
            order.append(g)
        buckets[g].append(n)
    picked, used = [], set()
    while len(picked) < k:
        progressed = False
        for g in order:
            while buckets.get(g):
                n = buckets[g].pop(0)
                if n["title"] in used:
                    continue
                used.add(n["title"])
                picked.append(n)
                progressed = True
                break
            if len(picked) >= k:
                break
        if not progressed:
            break
    return picked


def llm_enrich(papers, news):
    """可选：用 LLM 生成中文简报正文（一二部分）。失败返回 None 走兜底。"""
    if not LLM_API_KEY:
        return None
    papers_payload = [{"title": p["title"], "authors": p["authors"], "url": p["url"], "summary": p["summary"]} for p in papers]
    news_payload = [{"title": n["title"], "link": n["link"], "summary": n.get("summary", "")} for n in news]
    sys_p = ("你是「多传感器融合导航」领域每日简报助手。根据以下 arXiv 论文与行业新闻，"
             "生成中文简报正文(markdown，不要总标题)：\n"
             "【论文】%s\n【新闻】%s\n"
             "要求：\n一、论文(≤%d篇,时间倒序，来自近90天池的每日轮换，不必全是当天新发)：每篇 `[标题](url)` | 代码✅/❌/❓ | SOTA✅/❓ | "
             "**仅1-2句**中文创新点(≤45字，说明用了什么融合方法/新架构、解决什么痛点；代码/SOTA据摘要可判定性标✅/❌/❓)。\n"
             "二、行业资讯(≤%d条)：覆盖自动驾驶行业、智驾公司（华为/特斯拉/新势力/Robotaxi等）、量产与政策，可含少量传感器融合技术资讯；不要全是技术教程。每条**仅1句**中文要点(基于标题与摘要，突出事件/政策/量产/公司动向等要害，≤40字) + `[来源](link)`。\n"
             "只输出这两部分 markdown，不要多余解释。" % (
                 json.dumps(papers_payload, ensure_ascii=False),
                 json.dumps(news_payload, ensure_ascii=False),
                 PAPER_LIMIT, NEWS_LIMIT))
    payload = {"model": LLM_MODEL, "messages": [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": "请生成简报正文。"},
    ], "temperature": 0.3}
    # V4 Flash 默认思考模式，简报提炼不需要，关掉更稳更快
    if "deepseek" in (LLM_MODEL + LLM_BASE_URL).lower():
        payload["thinking"] = {"type": "disabled"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(LLM_BASE_URL + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                           "Authorization": "Bearer %s" % LLM_API_KEY},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read().decode("utf-8"))
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return content.strip() or None
    except Exception as e:
        log("llm enrich failed, fallback: %s" % e)
        return None


def fallback_body(papers, news):
    p_lines = []
    for p in papers:
        snippet = re.sub(r"\s+", " ", p["summary"])[:130]
        p_lines.append("**[%s](%s)**\n> 代码❓ | SOTA❓\n> 摘要：%s" % (p["title"], p["url"], snippet))
    paper_block = "\n\n".join(p_lines) if p_lines else "今日无新增论文"
    n_lines = []
    for i, n in enumerate(news):
        s = n.get("summary", "")
        summ_line = ("\n> %s" % s) if s else ""
        n_lines.append("%d. **%s**%s\n   [来源](%s)" % (i + 1, n["title"], summ_line, n["link"]))
    news_block = "\n".join(n_lines) if n_lines else "今日无重大行业资讯"
    return ("## 一、论文（≤%d 篇）\n%s\n\n## 二、行业资讯（≤%d 条）\n%s"
            % (PAPER_LIMIT, paper_block, NEWS_LIMIT, news_block))


WX_MD_LIMIT = 3500  # 企业微信 markdown 上限 4096 字节，留余量


def post_markdown(content):
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content}},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8")
    log("post: %s (%d bytes)" % (raw, len(content.encode("utf-8"))))
    try:
        err = json.loads(raw).get("errcode", 0)
    except Exception:
        err = -1
    if err:
        raise RuntimeError("wecom post failed: %s" % raw)
    return raw


def split_markdown_chunks(content, limit=WX_MD_LIMIT):
    """按段落切到企业微信字节上限以内。"""
    if len(content.encode("utf-8")) <= limit:
        return [content]
    parts = re.split(r"(\n{2,})", content)
    chunks, buf = [], ""
    for part in parts:
        cand = buf + part
        if buf and len(cand.encode("utf-8")) > limit:
            chunks.append(buf.rstrip())
            buf = part.lstrip("\n")
            if len(buf.encode("utf-8")) <= limit:
                continue
            # 单段仍超长：按行再切
            line_buf = ""
            for line in buf.split("\n"):
                cand_l = (line_buf + "\n" + line) if line_buf else line
                if line_buf and len(cand_l.encode("utf-8")) > limit:
                    chunks.append(line_buf)
                    line_buf = line
                else:
                    line_buf = cand_l
            buf = line_buf
        else:
            buf = cand
    if buf.strip():
        chunks.append(buf.rstrip())
    return [c for c in chunks if c.strip()]


def post_briefing(content):
    chunks = split_markdown_chunks(content)
    if len(chunks) > 1:
        log("content split into %d messages" % len(chunks))
    for i, chunk in enumerate(chunks):
        post_markdown(chunk)
        if i + 1 < len(chunks):
            time.sleep(0.4)


def main():
    today = now_bjt().date()
    since = today - datetime.timedelta(days=PAPER_LOOKBACK_DAYS)
    state = load_state()
    pushed_ids = state.get("pushed_paper_ids") or []
    recent_news = state.get("news_titles", [])

    arxiv_all = fetch_arxiv(since)
    new_papers = pick_papers(arxiv_all, pushed_ids, PAPER_LIMIT)

    news_all = fetch_news()
    new_news = [n for n in news_all if n["title"] not in set(recent_news)]
    new_news = pick_diverse_news(new_news, NEWS_LIMIT)
    log("news pick: " + " | ".join("%s[%s]" % (n.get("group", "?"), n["title"][:24]) for n in new_news))

    date_str = today.isoformat()
    if not new_papers and not new_news:
        body = "📡 多传感器融合导航每日简报 · %s：今日无新增内容" % date_str
        log("post: " + post_markdown(body))
        save_state({"pushed_paper_ids": pushed_ids[-PAPER_ID_KEEP:],
                    "news_titles": recent_news[-40:],
                    "last_run": now_bjt().isoformat()})
        return

    enriched = llm_enrich(new_papers, new_news)
    if enriched:
        body_mid = enriched
    else:
        body_mid = fallback_body(new_papers, new_news)
    header = "📡 **多传感器融合导航每日简报 · %s**\n\n" % date_str
    notes = ("\n\n> 说明：论文取自 arXiv 近%d天池（每日轮换未推过的，不要求当天新发）；行业资讯来自搜狗微信搜索，覆盖自动驾驶行业、智驾公司与相关技术，"
             "摘要为文章开头片段仅供参考。"
             % PAPER_LOOKBACK_DAYS
             if not LLM_API_KEY else
             "\n\n> 说明：内容由 LLM 中文提炼；论文取自 arXiv 近%d天池每日轮换，行业资讯覆盖自动驾驶行业、智驾公司与相关技术。"
             % PAPER_LOOKBACK_DAYS)
    content = header + body_mid + notes
    post_briefing(content)

    save_state({"pushed_paper_ids": update_pushed_ids(pushed_ids, new_papers),
                "news_titles": (recent_news + [n["title"] for n in new_news])[-40:],
                "last_run": now_bjt().isoformat()})
    log("done. papers=%d news=%d llm=%s" % (
        len(new_papers), len(new_news), "on" if LLM_API_KEY else "off"))


if __name__ == "__main__":
    if not WEBHOOK:
        sys.stderr.write("缺少 WECOM_WEBHOOK：请复制 .llm.env.example 为 .llm.env 并填入企业微信机器人地址。\n")
        sys.exit(1)
    main()
