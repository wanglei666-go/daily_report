# 领域每日简报

每天自动汇总 **arXiv 论文** 与 **行业资讯**，整理成一条中文简报，推送到企业微信群。

换领域只改配置，不用改代码。适合课题组、实验室或需要跟进某一方向的小团队。

---

## 功能

- **论文**：按关键词从 arXiv 抓取；近 90 天做成池子轮换推送，不依赖当天必须有新投稿
- **资讯**：优先搜狗微信（公众号），也可使用 Bing / Google News 或自定义 RSS
- **提炼**：可接入 DeepSeek、OpenAI 等兼容接口，将摘要压成几句中文要点；不接入也能运行
- **推送**：企业微信群机器人；内容过长时自动拆成多条
- **轻量**：仅 Python 3 标准库，无需安装第三方包；不占用 GPU

论文标题与 arXiv 链接由程序本地组装，与正文一一对应。

---

## 推送效果示例

```text
📡 多传感器融合导航每日简报 · 2026-08-19

## 一、论文
[论文标题](https://arxiv.org/abs/xxxx.xxxxx)
> 代码❓ | SOTA✅
> 一两句中文创新点……

## 二、行业资讯
1. **行业或公司动态标题**
> 一句要点
   [来源](...)
```

仓库提供完整示例配置（多传感器融合 / 自动驾驶）：`topics.examples/sensor-fusion.json`。

---

## 使用步骤

### 1. 获取代码

```bash
git clone https://github.com/wanglei666-go/daily_report.git
cd daily_report
```

### 2. 准备配置文件

```bash
cp topics.example.json topics.json
cp .llm.env.example .llm.env
```

若希望直接使用传感器融合示例：

```bash
cp topics.examples/sensor-fusion.json topics.json
```

### 3. 配置企业微信机器人

在目标群中：群设置 → 群机器人 → 添加，复制 webhook，写入 `.llm.env`：

```bash
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
```

### 4. （可选）配置 LLM

用于中文提炼。未配置时，论文部分使用英文摘要。

```bash
LLM_API_KEY=sk-你的key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

### 5. 试运行

```bash
python3 briefing_server.py
```

群内收到简报，且输出中出现 `errcode:0` 即表示成功。

### 6. 定时每天发送

在常开服务器上配置 cron（示例：每天 09:30，北京时间）：

```bash
chmod +x run_briefing.sh
crontab -e
```

```cron
MAILTO=""
TZ=Asia/Shanghai
30 9 * * * /你的安装路径/daily_report/run_briefing.sh
```

---

## 配置项说明

### `topics.json`

| 字段 | 含义 |
| --- | --- |
| `domain` | 领域名称 |
| `title` | 简报标题；为空时使用「{domain}每日简报」 |
| `arxiv_keywords` | arXiv 检索词；同一组内为 AND，组与组之间为 OR |
| `weixin_query_groups` | 公众号检索，建议按 industry / company / tech 分组 |
| `news_queries` | Bing / Google 检索词 |
| `news_rss_feeds` | 自定义 RSS 地址列表 |
| `paper_must_include_any` / `paper_also_include_any` | 论文标题与摘要的额外过滤词，可为空 |
| `paper_exclude` | 排除词 |
| `news_focus` | 资讯侧关注重点，供 LLM 参考 |
| `paper_limit` / `news_limit` / `paper_lookback_days` | 每天论文篇数、资讯条数、论文回溯天数 |

### `.llm.env`

| 变量 | 是否必需 | 含义 |
| --- | --- | --- |
| `WECOM_WEBHOOK` | 是 | 企业微信机器人 webhook |
| `LLM_API_KEY` | 否 | LLM 密钥 |
| `LLM_BASE_URL` / `LLM_MODEL` | 否 | 接口地址与模型名 |

---

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `briefing_server.py` | 主程序 |
| `run_briefing.sh` | 定时任务启动脚本 |
| `topics.example.json` | 领域配置模板 |
| `topics.examples/` | 可直接套用的领域示例 |
| `.llm.env.example` | 密钥配置模板 |
