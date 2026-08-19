# Daily Report · 领域每日简报

每天自动把 **arXiv 新论文** 和 **行业资讯** 汇总成一条中文简报，推到企业微信群。

适合课题组、实验室、产品团队：不想每天手翻 arXiv / 公众号，又希望信息别太散。

[English summary](#english-summary) · [快速开始](#快速开始) · [配置说明](#配置说明) · [常见问题](#常见问题)

---

## 它能做什么

| | |
| --- | --- |
| 论文 | 按你设定的关键词从 arXiv 抓取，近 90 天池子轮换，保证几乎每天都有内容 |
| 资讯 | 优先搜狗微信（公众号），可选 Bing / Google News / 自定义 RSS |
| 提炼 | 可选接入 DeepSeek / OpenAI 等兼容接口，把长摘要压成几句中文要点 |
| 推送 | 企业微信群机器人；内容过长会自动拆成多条 |
| 领域 | **不写死某一学科**——换 LLM、机器人、生物、材料……只改配置文件 |

**资源很轻**：纯 Python 3 标准库，无需 `pip install`；不占 GPU；跑完约 1 分钟就退出。

**链接靠谱**：论文标题和 arXiv 链接由本地代码固定组装，不会因为 LLM「改写」而对错篇。

---

## 效果长什么样

推到群里大致是：

```text
📡 多传感器融合导航每日简报 · 2026-08-19

## 一、论文
[论文标题](https://arxiv.org/abs/xxxx.xxxxx)
> 代码❓ | SOTA✅
> 一两句中文创新点……

## 二、行业资讯
1. **某公司量产/政策动态**
> 一句要点
   [来源](...)
```

仓库里带了一个完整示例配置：多传感器融合 / 自动驾驶（`topics.examples/sensor-fusion.json`）。换成你自己的领域即可。

---

## 快速开始

### 1. 拿到代码

```bash
git clone https://github.com/wanglei666-go/daily_report.git
cd daily_report
```

### 2. 复制两份配置

```bash
cp topics.example.json topics.json          # 领域：论文词、资讯词
cp .llm.env.example .llm.env                # 密钥：企业微信；可选 LLM
```

想先跑通「传感器融合」示例：

```bash
cp topics.examples/sensor-fusion.json topics.json
```

### 3. 填企业微信机器人（必填）

1. 打开目标企业微信群 → 群设置 → 群机器人 → 添加  
2. 复制 webhook 完整 URL  
3. 写入 `.llm.env`：

```bash
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
```

### 4.（可选）开 LLM 中文提炼

不配也能跑，论文会用英文摘要兜底。推荐 DeepSeek 等 OpenAI 兼容接口：

```bash
LLM_API_KEY=sk-你的key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

### 5. 试跑一次

```bash
python3 briefing_server.py
```

群里出现简报，且终端/日志里有 `post: {"errcode":0,"errmsg":"ok"}` 就成功了。

### 6. 设成每天自动发

机器保持开机，安装 cron 后：

```bash
chmod +x run_briefing.sh
crontab -e
```

加入（把路径改成你本机的绝对路径；下面是每天 09:30 北京时间）：

```cron
MAILTO=""
TZ=Asia/Shanghai
30 9 * * * /你的路径/daily_report/run_briefing.sh
```

退出 SSH 也会继续跑。查看任务：`crontab -l`。日志文件：`briefing.log`。

---

## 配置说明

### `topics.json`（领域）

| 字段 | 说明 |
| --- | --- |
| `domain` | 领域中文名（标题、LLM 提示都会用到） |
| `title` | 简报标题；可留空，默认「{domain}每日简报」 |
| `arxiv_keywords` | arXiv 检索：每组内 AND，组之间 OR。例 `["sensor fusion","SLAM"]` |
| `weixin_query_groups` | 公众号关键词，建议分 `industry` / `company` / `tech`，简报会轮询取条 |
| `news_queries` | Bing / Google 检索词（境内常不稳定，作兜底） |
| `news_rss_feeds` | 可选自定义 RSS |
| `paper_must_include_any` / `paper_also_include_any` | 标题+摘要还需命中的英文词；可留空 |
| `paper_exclude` | 命中则丢弃（挡离题论文） |
| `news_focus` | 告诉 LLM 资讯侧要突出什么 |
| `paper_limit` / `news_limit` / `paper_lookback_days` | 每天篇数、资讯条数、论文池窗口（默认 90 天） |

改领域 = 改这个文件，一般不用动 Python 代码。

### `.llm.env`（密钥）

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `WECOM_WEBHOOK` | 是 | 企业微信机器人完整 URL |
| `LLM_API_KEY` | 否 | 有则中文提炼；无则英文摘要兜底 |
| `LLM_BASE_URL` / `LLM_MODEL` | 否 | OpenAI 兼容接口地址与模型名 |

**不要把 `.llm.env`、`topics.json`、真实 key 提交到 Git。** 仓库已用 `.gitignore` 排除运行产物与本地密钥。

---

## 仓库里有什么

```text
briefing_server.py      # 主脚本
run_briefing.sh         # cron 启动包装
topics.example.json     # 空白领域模板
topics.examples/        # 可直接复制的完整示例
.llm.env.example        # 密钥模板
.gitignore
```

运行后本地还会生成（请勿提交）：

- `briefing_state.json`：去重与论文缓存  
- `briefing.log`：运行日志  

---

## 常见问题

**Q：今天 arXiv 没有新论文，还会推吗？**  
会。脚本维护近 N 天论文池，优先推「还没推过」的；推完一轮再循环。不要求必须当天新投稿。

**Q：点开论文链接发现不是这篇？**  
当前版本链接由本地组装，不再让模型自己写 URL。若你用的是很早的旧副本，请更新到本仓库最新代码。

**Q：早高峰 arXiv 报 429 / 超时？**  
会自动重试；仍失败则使用上次成功的 `paper_cache`，当天仍可继续轮换推送。

**Q：占不占显卡？**  
不占。LLM 在云端 API 推理，本机只是普通 HTTP 请求。

**Q：能推飞书 / 钉钉吗？**  
当前默认企业微信 markdown webhook。改推送通道需要改 `post_markdown` 一段（欢迎 PR）。

---

## English Summary

A tiny, dependency-free Python 3 daily digester: pull arXiv papers + industry news for **any topic you configure**, optionally summarize with an OpenAI-compatible LLM, and push markdown to a WeCom (企业微信) group bot.

1. Clone → copy `topics.example.json` / `.llm.env.example`  
2. Fill `WECOM_WEBHOOK` (required) and optional `LLM_API_KEY`  
3. `python3 briefing_server.py` once, then schedule with cron  

Paper titles and arXiv links are assembled locally (not by the LLM), so links stay consistent with titles.

---

## License / 使用说明

按自己需要使用、修改即可。分享配置时请打码 webhook 与 API key。
