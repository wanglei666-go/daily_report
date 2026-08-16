# 多传感器融合导航每日简报

独立 Python 脚本：每天从 arXiv 抓相关论文、从公众号/新闻源抓自动驾驶与智驾行业资讯，可选调用 LLM 写成中文简报，推送到企业微信群机器人。

仅依赖 **Python 3 标准库**，无需 `pip install`。不占用 GPU，运行约 1 分钟后退出。

## 功能

- **论文**：arXiv 近 90 天「传感器融合 / 导航 / SLAM」相关论文；按已推送 ID 轮换，保证每天有内容，不要求当天必须有新投稿
- **资讯**：搜狗微信搜索为主（行业 / 智驾公司 / 技术三类轮询），Bing / Google News 作境内不可用时的兜底
- **LLM（可选）**：OpenAI 兼容接口，把论文创新点和资讯压成中文要点；未配置或调用失败时自动用英文摘要兜底
- **推送**：企业微信 markdown；超长自动拆成多条（单条上限约 4096 字节）

## 仓库里有什么

| 文件 | 说明 |
| --- | --- |
| `briefing_server.py` | 主脚本 |
| `run_briefing.sh` | cron 启动包装（路径相对脚本目录） |
| `.llm.env.example` | 配置模板，复制为 `.llm.env` 后填写 |

以下文件**不要提交**，已写入 `.gitignore`：

- `.llm.env`（webhook、API key）
- `briefing_state.json`（去重状态）
- `briefing.log`

## 快速开始

```bash
git clone <your-repo-url>
cd <repo-dir>
cp .llm.env.example .llm.env
```

编辑 `.llm.env`：

```bash
# 必填：企业微信群机器人 webhook
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key

# 可选：LLM（任意 OpenAI 兼容服务）
LLM_API_KEY=sk-你的key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

企业微信机器人：群设置 → 群机器人 → 添加 → 复制 webhook。

试跑一次：

```bash
python3 briefing_server.py
```

看到群消息、日志里有 `post: {"errcode":0,"errmsg":"ok"}` 即成功。

## 每天定时发送

机器需常开，且已安装 cron。下面以每天 09:30（Asia/Shanghai）为例：

```bash
chmod +x run_briefing.sh
crontab -e
```

加入：

```cron
MAILTO=""
TZ=Asia/Shanghai
30 9 * * * /绝对路径/run_briefing.sh
```

这是系统 crontab，退出 SSH / 编辑器后仍会执行。查看任务：`crontab -l`。日志：`briefing.log`。

## 可调参数

在 `briefing_server.py` 顶部：

- `PAPER_LIMIT` / `PAPER_LOOKBACK_DAYS`：每天论文篇数、论文池窗口
- `NEWS_LIMIT`、`WEIXIN_QUERY_GROUPS`、`NEWS_QUERIES`：资讯条数与检索词
- `NEWS_RSS_FEEDS`：可追加国内媒体 RSS

## 资源占用

不使用 GPU。内存大约几十 MB，每天跑完即退出。LLM 在云端 API 推理，不在本机加载模型。

## 安全

- 不要把 `.llm.env`、真实 webhook、API key 提交到 git
- 若 key 曾经出现在公开仓库或聊天记录中，请在对应平台轮换
- 机器人 webhook 等同于向该群发消息的凭证，泄露后应在企业微信中重置
