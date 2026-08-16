# 领域每日简报

独立 Python 脚本：按你在 `topics.json` 里填写的领域，每天从 arXiv 抓论文、从公众号/新闻源抓行业资讯，可选调用 LLM 写成中文简报，推送到企业微信群机器人。

仅依赖 **Python 3 标准库**，无需 `pip install`。不占用 GPU，运行约 1 分钟后退出。

领域不写死。换课题时只改配置文件，不用改代码。

## 你需要填的两份配置

| 文件 | 作用 |
| --- | --- |
| `topics.json` | **领域**：论文关键词、资讯检索词、简报标题 |
| `.llm.env` | **密钥**：企业微信 webhook；可选 LLM key |

模板：

```bash
cp topics.example.json topics.json
cp .llm.env.example .llm.env
```

完整可用示例（多传感器融合导航）在 `topics.examples/sensor-fusion.json`，可直接复制后改：

```bash
cp topics.examples/sensor-fusion.json topics.json
```

## 1. 填写领域 `topics.json`

必填：

- `domain`：领域中文名，会出现在标题和 LLM 提示里
- `arxiv_keywords`：arXiv 检索。每一项是一组英文词（同一组内 AND，组与组之间 OR）
- 资讯三选一即可：`weixin_query_groups`（公众号，境内最稳）、`news_queries`（Bing/Google）、`news_rss_feeds`

常用选填：

- `title`：简报标题；留空则用「{domain}每日简报」
- `news_focus`：告诉 LLM 资讯侧要覆盖什么；留空则用「{domain}行业、相关公司与技术动态」
- `paper_must_include_any` / `paper_also_include_any`：标题+摘要还需命中的英文词（可留空）
- `paper_exclude`：命中则丢弃
- `paper_limit` / `news_limit` / `paper_lookback_days`

`arxiv_keywords` 示例：要搜同时含 A 和 B 的论文，写成 `["A", "B"]`；只要其中一个词，写成单独一组 `["A"]`。

## 2. 填写密钥 `.llm.env`

```bash
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key

# 可选。不填则推送英文摘要兜底
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

企业微信：群设置 → 群机器人 → 添加 → 复制 webhook。

## 试跑

```bash
python3 briefing_server.py
```

群里收到消息，且日志出现 `post: {"errcode":0,"errmsg":"ok"}` 即成功。

## 每天定时发送

机器需常开并已安装 cron。以每天 09:30（Asia/Shanghai）为例：

```bash
chmod +x run_briefing.sh
crontab -e
```

```cron
MAILTO=""
TZ=Asia/Shanghai
30 9 * * * /绝对路径/run_briefing.sh
```

这是系统 crontab，退出 SSH 后仍会执行。查看：`crontab -l`。日志：`briefing.log`。

## 论文怎么保证每天都有

从 arXiv 近 N 天（默认 90）做成池子，按已推送 ID 轮换：优先未推过的，推完再循环。不要求当天必须有新投稿。

## 仓库文件

| 文件 | 说明 |
| --- | --- |
| `briefing_server.py` | 主脚本 |
| `run_briefing.sh` | cron 包装（路径相对脚本目录） |
| `topics.example.json` | 领域配置模板 |
| `topics.examples/` | 可直接复制的完整示例 |
| `.llm.env.example` | 密钥模板 |

不要提交：`.llm.env`、`topics.json`、`briefing_state.json`、`briefing.log`（已写入 `.gitignore`）。

## 资源占用

不使用 GPU。内存大约几十 MB，跑完即退出。LLM 在云端 API 推理。

## 安全

- 不要把 `.llm.env`、真实 webhook、API key 提交到 git 或发到公开仓库
- 机器人 webhook 等同于向该群发消息的凭证，泄露后应在企业微信中重置
