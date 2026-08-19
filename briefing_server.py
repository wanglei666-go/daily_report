#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
领域每日简报 —— 独立脚本
论文 / 资讯领域由同目录 topics.json 配置，不写死某一学科。
密钥走环境变量或 .llm.env（不要提交到 git）：
  WECOM_WEBHOOK   企业微信群机器人 webhook 完整 URL
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL   可选，OpenAI 兼容接口
依赖：仅 Python3 标准库。

论文标题与链接由本地组装；LLM 只生成中文要点，避免链接错配。
arXiv 失败时回退 paper_cache，保证每日仍能轮换推送。
"""
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
import json, datetime, re, os, gzip, sys, time, html

_HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_HERE, "briefing_state.json")
LOG_FILE = os.path.join(_HERE, "briefing.log")
LLM_ENV_FILE = os.path.join(_HERE, ".llm.env")
TOPICS_FILE = os.path.join(_HERE, "topics.json")
BJT = datetime.timezone(datetime.timedelta(hours=8))


def _load_llm_env_file():
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


def _as_str_list(v):
    out = []
    for x in v or []:
        s = str(x).strip()
        if s:
            out.append(s)
    return out


def _build_arxiv_query(cfg):
    raw = (cfg.get("arxiv_query") or "").strip()
    if raw:
        return raw
    groups = []
    for item in cfg.get("arxiv_keywords") or []:
        if isinstance(item, str):
            terms = [item]
        else:
            terms = list(item)
        terms = [t.strip().replace('"', "") for t in terms if str(t).strip()]
        if not terms:
            continue
        if len(terms) == 1:
            groups.append('all:"%s"' % terms[0])
        else:
            groups.append("(" + " AND ".join('all:"%s"' % t for t in terms) + ")")
    if not groups:
        sys.stderr.write("topics.json 需要填写 arxiv_keywords（或 arxiv_query）。\n")
        sys.exit(1)
    return " OR ".join(groups)


def _weixin_groups(cfg):
    raw = cfg.get("weixin_query_groups") or {}
    if isinstance(raw, list):
        return [(g, _as_str_list(qs)) for g, qs in raw if _as_str_list(qs)]
    out = []
    for name in ("industry", "company", "tech"):
        qs = _as_str_list(raw.get(name))
        if qs:
            out.append((name, qs))
    for name, qs in raw.items():
        if name in ("industry", "company", "tech"):
            continue
        qs = _as_str_list(qs)
        if qs:
            out.append((name, qs))
    return out


def load_topics():
    if not os.path.isfile(TOPICS_FILE):
        sys.stderr.write(
            "缺少 topics.json。请先：\n"
            "  cp topics.example.json topics.json\n"
            "然后按自己的领域改检索词。完整示例见 topics.examples/\n")
        sys.exit(1)
    with open(TOPICS_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    domain = (cfg.get("domain") or "").strip()
    if not domain or domain.startswith("在这里填写"):
        sys.stderr.write("请在 topics.json 里把 domain 改成你的领域中文名。\n")
        sys.exit(1)
    title = (cfg.get("title") or "").strip() or (domain + "每日简报")
    news_focus = (cfg.get("news_focus") or "").strip() or (domain + "行业、相关公司与技术动态")
    paper_core = [k.lower() for k in _as_str_list(cfg.get("paper_must_include_any"))]
    paper_also = [k.lower() for k in _as_str_list(cfg.get("paper_also_include_any"))]
    paper_core = [k for k in paper_core if "至少命中" not in k and "可留空" not in k]
    weixin = _weixin_groups(cfg)
    news_queries = _as_str_list(cfg.get("news_queries"))
    if not weixin and not news_queries and not _as_str_list(cfg.get("news_rss_feeds")):
        sys.stderr.write("topics.json 需要至少填写 weixin_query_groups、news_queries 或 news_rss_feeds 之一。\n")
        sys.exit(1)
    return {
        "domain": domain,
        "title": title,
        "news_focus": news_focus,
        "arxiv_query": _build_arxiv_query(cfg),
        "paper_core": paper_core,
        "paper_also": paper_also,
        "paper_exclude": [k.lower() for k in _as_str_list(cfg.get("paper_exclude"))],
        "news_queries": news_queries,
        "weixin_query_groups": weixin,
        "news_rss_feeds": _as_str_list(cfg.get("news_rss_feeds")),
        "paper_limit": int(cfg.get("paper_limit") or 5),
        "news_limit": int(cfg.get("news_limit") or 8),
        "paper_lookback_days": int(cfg.get("paper_lookback_days") or 90),
        "paper_id_keep": int(cfg.get("paper_id_keep") or 240),
    }


_load_llm_env_file()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
WEBHOOK = (os.environ.get("WECOM_WEBHOOK") or os.environ.get("WEBHOOK") or "").strip()
TOPICS = load_topics() if os.path.isfile(TOPICS_FILE) else {}

ARXIV_QUERY = TOPICS.get("arxiv_query", "")
PAPER_LIMIT = TOPICS.get("paper_limit", 5)
PAPER_LOOKBACK_DAYS = TOPICS.get("paper_lookback_days", 90)
PAPER_ID_KEEP = TOPICS.get("paper_id_keep", 240)
NEWS_LIMIT = TOPICS.get("news_limit", 8)
NEWS_QUERIES = TOPICS.get("news_queries", [])
NEWS_RSS_FEEDS = TOPICS.get("news_rss_feeds", [])
WEIXIN_QUERY_GROUPS = TOPICS.get("weixin_query_groups", [])
CORE = TOPICS.get("paper_core", [])
FUS = TOPICS.get("paper_also", [])
BLOCK = TOPICS.get("paper_exclude", [])
BRIEF_TITLE = TOPICS.get("title", "每日简报")
DOMAIN = TOPICS.get("domain", "")
NEWS_FOCUS = TOPICS.get("news_focus", "")


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


def _paper_ok(text):
    t = text.lower()
    if any(b in t for b in BLOCK):
        return False
    if CORE and sum(k in t for k in CORE) < 1:
        return False
    if FUS and sum(k in t for k in FUS) < 1:
        return False
    return True


def _norm_arxiv_url(aid_or_url):
    s = (aid_or_url or "").strip()
    if "/abs/" in s:
        arxiv_id = s.split("/abs/")[-1].strip()
    else:
        arxiv_id = s
    arxiv_id = arxiv_id.split("?")[0].strip()
    return "https://arxiv.org/abs/%s" % arxiv_id, arxiv_id


def fetch_arxiv(since_date):
    papers = {}
    url = ("https://export.arxiv.org/api/query?search_query=%s"
           "&sortBy=submittedDate&sortOrder=descending&max_results=200"
           % urllib.parse.quote(ARXIV_QUERY))
    data = None
    for attempt in range(4):
        try:
            data = http_get(url, timeout=45)
            break
        except Exception as e:
            wait = 8 * (attempt + 1)
            log("arxiv query failed (attempt %d): %s; sleep %ds" % (attempt + 1, e, wait))
            time.sleep(wait)
    if not data:
        log("arxiv 全部请求失败，本次跳过在线抓取")
        return papers
    for m in re.finditer(r"<entry>(.*?)</entry>", data, re.S):
        e = m.group(1)
        aid = re.search(r"<id>(.*?)</id>", e)
        if not aid or "/abs/" not in aid.group(1):
            continue
        url_abs, arxiv_id = _norm_arxiv_url(aid.group(1))
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
        if not _paper_ok(title + " " + summary):
            continue
        if arxiv_id not in papers:
            papers[arxiv_id] = {"arxiv_id": arxiv_id, "title": title,
                                "published": published, "summary": summary,
                                "authors": authors, "url": url_abs}
    return papers


def load_paper_cache(state):
    cache = state.get("paper_cache") or {}
    out = {}
    for aid, p in cache.items():
        if not isinstance(p, dict) or not p.get("title"):
            continue
        url, arxiv_id = _norm_arxiv_url(p.get("url") or aid)
        out[arxiv_id] = {
            "arxiv_id": arxiv_id,
            "title": p.get("title", ""),
            "published": p.get("published", ""),
            "summary": p.get("summary", ""),
            "authors": p.get("authors", ""),
            "url": url,
        }
    return out


def save_paper_cache(papers):
    return {aid: {"arxiv_id": p["arxiv_id"], "title": p["title"], "published": p["published"],
                  "summary": p.get("summary", "")[:500], "authors": p.get("authors", ""),
                  "url": p["url"]} for aid, p in papers.items()}


def pick_papers(arxiv_all, pushed_ids, k=PAPER_LIMIT):
    pushed_ids = list(pushed_ids or [])
    pushed_set = set(pushed_ids)
    unseen = [p for aid, p in arxiv_all.items() if aid not in pushed_set]
    unseen.sort(key=lambda p: p["published"], reverse=True)
    picked = unseen[:k]
    n_fresh = len(picked)
    if len(picked) < k:
        picked_ids = set(p["arxiv_id"] for p in picked)
        for aid in pushed_ids:
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
    today_ids = [p["arxiv_id"] for p in picked]
    today_set = set(today_ids)
    rest = [i for i in (pushed_ids or []) if i not in today_set]
    return (rest + today_ids)[-PAPER_ID_KEEP:]


def _parse_rss_items(data):
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
    items, seen = [], set()
    for group, queries in WEIXIN_QUERY_GROUPS:
        for q in queries:
            url = "https://weixin.sogou.com/weixin?type=2&query=%s&ie=utf8" % urllib.parse.quote(q)
            try:
                data = http_get(url)
            except Exception as e:
                log("weixin search failed (%s): %s" % (q, e))
                continue
            for b in data.split('<div class="txt-box">')[1:]:
                links = re.findall(r'<a[^>]*href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>', b, re.S)
                mlink = None
                for href, t in links:
                    if html.unescape(re.sub(r"<[^>]+>", "", t)).strip():
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


def _parse_llm_json(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def llm_enrich(papers, news):
    """LLM 只返回中文要点 JSON；标题与链接一律由本地组装。"""
    if not LLM_API_KEY:
        return None
    papers_payload = [{
        "id": p["arxiv_id"],
        "title": p["title"],
        "summary": p["summary"][:900],
    } for p in papers]
    news_payload = [{
        "i": i,
        "title": n["title"],
        "summary": n.get("summary", ""),
    } for i, n in enumerate(news)]
    sys_p = (
        "你是「%s」领域每日简报助手。根据给定论文与新闻，只输出一个 JSON 对象，不要 markdown，不要编造论文或链接。\n"
        "格式：{\"papers\":[{\"id\":\"与输入完全一致的arxiv id\",\"code\":\"✅或❌或❓\",\"sota\":\"✅或❓\",\"blurb\":\"中文1-2句≤45字\"}],"
        "\"news\":[{\"i\":0,\"blurb\":\"中文1句≤40字\"}]}\n"
        "规则：papers/news 条数分别不超过输入；id/i 必须来自输入；不要输出 url；没有内容时对应数组为空。\n"
        "资讯侧请覆盖：%s\n"
        "【论文】%s\n【新闻】%s" % (
            DOMAIN, NEWS_FOCUS,
            json.dumps(papers_payload, ensure_ascii=False),
            json.dumps(news_payload, ensure_ascii=False),
        )
    )
    payload = {"model": LLM_MODEL, "messages": [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": "请只输出 JSON。"},
    ], "temperature": 0.2}
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
        raw = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        data = _parse_llm_json(raw)
        if not isinstance(data, dict):
            log("llm enrich: JSON parse failed")
            return None
        return assemble_body(papers, news, data)
    except Exception as e:
        log("llm enrich failed, fallback: %s" % e)
        return None


def assemble_body(papers, news, llm_data=None):
    llm_data = llm_data or {}
    paper_meta = {}
    for item in llm_data.get("papers") or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if pid:
            paper_meta[pid] = item
            paper_meta[pid.split("v")[0]] = item

    p_lines = []
    for p in papers:
        meta = paper_meta.get(p["arxiv_id"]) or paper_meta.get(p["arxiv_id"].split("v")[0]) or {}
        code = meta.get("code") if meta.get("code") in ("✅", "❌", "❓") else "❓"
        sota = meta.get("sota") if meta.get("sota") in ("✅", "❓") else "❓"
        blurb = re.sub(r"\s+", " ", str(meta.get("blurb") or "").strip())
        if not blurb:
            blurb = re.sub(r"\s+", " ", p["summary"])[:90]
        p_lines.append("**[%s](%s)**\n> 代码%s | SOTA%s\n> %s" % (
            p["title"], p["url"], code, sota, blurb))
    paper_block = "\n\n".join(p_lines) if p_lines else "今日无新增论文"

    news_meta = {}
    for item in llm_data.get("news") or []:
        if isinstance(item, dict) and "i" in item:
            try:
                news_meta[int(item["i"])] = item
            except Exception:
                pass

    n_lines = []
    for i, n in enumerate(news):
        meta = news_meta.get(i) or {}
        blurb = re.sub(r"\s+", " ", str(meta.get("blurb") or "").strip())
        if not blurb:
            blurb = n.get("summary") or ""
        if blurb:
            n_lines.append("%d. **%s**\n> %s\n   [来源](%s)" % (i + 1, n["title"], blurb, n["link"]))
        else:
            n_lines.append("%d. **%s**\n   [来源](%s)" % (i + 1, n["title"], n["link"]))
    news_block = "\n".join(n_lines) if n_lines else "今日无重大行业资讯"
    return ("## 一、论文（≤%d 篇）\n%s\n\n## 二、行业资讯（≤%d 条）\n%s"
            % (PAPER_LIMIT, paper_block, NEWS_LIMIT, news_block))


def fallback_body(papers, news):
    return assemble_body(papers, news, None)


WX_MD_LIMIT = 3500


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
    if arxiv_all:
        paper_cache = save_paper_cache(arxiv_all)
        log("arxiv online ok, pool=%d (cache refreshed)" % len(arxiv_all))
    else:
        arxiv_all = load_paper_cache(state)
        paper_cache = state.get("paper_cache") or save_paper_cache(arxiv_all)
        log("arxiv online failed, fallback cache pool=%d" % len(arxiv_all))

    new_papers = pick_papers(arxiv_all, pushed_ids, PAPER_LIMIT)

    news_all = fetch_news()
    new_news = [n for n in news_all if n["title"] not in set(recent_news)]
    new_news = pick_diverse_news(new_news, NEWS_LIMIT)
    log("news pick: " + " | ".join("%s[%s]" % (n.get("group", "?"), n["title"][:24]) for n in new_news))

    date_str = today.isoformat()
    if not new_papers and not new_news:
        body = "📡 %s · %s：今日无新增内容" % (BRIEF_TITLE, date_str)
        post_markdown(body)
        save_state({"pushed_paper_ids": pushed_ids[-PAPER_ID_KEEP:],
                    "news_titles": recent_news[-40:],
                    "paper_cache": paper_cache,
                    "last_run": now_bjt().isoformat()})
        return

    enriched = llm_enrich(new_papers, new_news)
    body_mid = enriched if enriched else fallback_body(new_papers, new_news)
    header = "📡 **%s · %s**\n\n" % (BRIEF_TITLE, date_str)
    notes = ("\n\n> 说明：论文取自 arXiv 近%d天池（每日轮换）；资讯覆盖%s。"
             % (PAPER_LOOKBACK_DAYS, NEWS_FOCUS)
             if not LLM_API_KEY else
             "\n\n> 说明：论文链接由本地固定组装；要点由 LLM 中文提炼。论文取自 arXiv 近%d天池；资讯覆盖%s。"
             % (PAPER_LOOKBACK_DAYS, NEWS_FOCUS))
    post_briefing(header + body_mid + notes)

    save_state({"pushed_paper_ids": update_pushed_ids(pushed_ids, new_papers),
                "news_titles": (recent_news + [n["title"] for n in new_news])[-40:],
                "paper_cache": paper_cache,
                "last_run": now_bjt().isoformat()})
    log("done. papers=%d news=%d llm=%s domain=%s" % (
        len(new_papers), len(new_news), "on" if LLM_API_KEY else "off", DOMAIN))


if __name__ == "__main__":
    if not os.path.isfile(TOPICS_FILE):
        load_topics()
    if not WEBHOOK:
        sys.stderr.write("缺少 WECOM_WEBHOOK：请复制 .llm.env.example 为 .llm.env 并填入企业微信机器人地址。\n")
        sys.exit(1)
    main()
