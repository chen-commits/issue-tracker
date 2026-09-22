# vLLM Ascend Issue 分析工具

一个只读同步 GitHub Issue 的轻量内部工具。GitHub 数据通过公共 REST API 获取，测试分析字段仅保存在本地 SQLite 中，不会评论、订阅、修改或关联上游 Issue。

## 功能

- 首次同步全部 `vllm-project/vllm-ascend` Issue
- 每 15 分钟按更新时间增量同步
- 点击“立即同步”时执行全量校准，可补回历史分页中遗漏的 Issue
- 支持使用 GLM 对单条 Issue 和评论生成结构化分析建议，人工确认后再保存
- 支持勾选 Issue 或按当前筛选结果创建持久化批量 AI 分析任务
- 批量建议独立保存，支持进度查看、失败重试、取消和人工采纳
- “优先处理”视图只显示已分析且较可复现、价值较高的非 Doc/RFC Issue，并按复现性、价值及明确版本信息排序
- 同步 Open/Closed 状态、标题、正文、标签、作者和时间
- 支持最近一个月、状态、识别结果、价值等级和结论状态筛选
- 支持问题分析、漏测原因、补充测试等人工字段
- HTTP Basic Auth 登录保护
- SQLite 单文件持久化

## 本地运行

复制配置文件并修改账号、密码等配置：

```bash
cp .env.example .env
```

Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x start.sh
./start.sh
```

后台日志默认写入 `logs/issue-tracker.log`，进程号写入 `issue-tracker.pid`。查看日志：

```bash
tail -f logs/issue-tracker.log
```

停止服务：

```bash
kill "$(cat issue-tracker.pid)"
```

Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\scripts\run.ps1
```

访问 `http://127.0.0.1:8080`。

## 目录结构

```text
issue-tracker/
|-- issue_tracker/
|   |-- __init__.py       # Python 包入口
|   |-- application.py    # Flask 路由、SQLite 和 GitHub 同步逻辑
|   |-- ai_analysis.py    # Issue 分析规则、提示词和结果校验
|   |-- llm_client.py     # 基于 OpenAI SDK 的兼容模型客户端
|   |-- batch_analysis.py # 持久化批量任务、分析记录和后台 Worker
|   `-- static/           # HTML、CSS 和 JavaScript
|-- scripts/
|   `-- run.ps1           # Windows 本地启动脚本
|-- tests/                # 自动化测试
|-- data/                 # SQLite 运行数据（自动创建）
|-- app.py                # 应用启动入口
|-- .env.example          # 配置文件模板
`-- requirements.txt
```

## AI 建议与优先处理

“漏测原因”保留为人工填写字段，AI 不再生成或覆盖它。“补充测试”会尽量整理 Issue 中明确给出的模型配置、A2/A3/A5 硬件、软件版本、触发场景和断言；缺失信息标记为“待确认”，不会虚构。更新后需重新批量分析，旧版 AI 记录没有复现性评级，不进入“优先处理”视图。该视图仅筛选和排序，不删除 Issue，也不修改已采纳的人工分析。筛选状态下创建批量任务时，仅分析当前视图中的 Issue。

优先级先看复现性（高、中），再看价值（高、中），然后参考明确写出的版本号与分析可信度。没有明确版本号的 Issue 不会被当作“新版本”优先；不同产品的版本号不会直接当作同一版本序列比较。Doc/RFC、非问题、低价值及复现性低或信息不足的 Issue 不出现在该视图，但仍保留在完整列表中。

## GitHub API 限额

公开仓库可以不配置 Token，但匿名 API 限额按出口 IP 共享。首次全量同步约发出 37 次分页请求，在公司代理或共享出口环境中应配置只读 `GITHUB_TOKEN`，否则可能在同步中途收到 HTTP 403。

应用仅包含 GitHub `GET /repos/{owner}/{repo}/issues` 请求，不包含写入 GitHub 的代码路径。

## 配置

应用启动时自动读取项目根目录的 `.env`。系统环境变量优先级更高，可通过系统环境变量 `ENV_FILE` 指定其他配置文件路径。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `APP_USERNAME` | `admin` | 登录账号 |
| `APP_PASSWORD` | `admin` | 登录密码，部署时必须修改 |
| `GITHUB_REPOSITORY` | `vllm-project/vllm-ascend` | 同步仓库 |
| `GITHUB_TOKEN` | 空 | 可选只读 Token |
| `GITHUB_SSL_VERIFY` | `true` | 是否校验 GitHub HTTPS 证书；仅在可信内网代理下可设为 `false` |
| `GITHUB_PAGE_SIZE` | `100` | 每次获取的 Issue 数量；代理不稳定时可降低到 `50` |
| `GITHUB_REQUEST_RETRIES` | `3` | GitHub 请求中断后的自动重试次数 |
| `SYNC_INTERVAL_MINUTES` | `15` | 自动同步间隔 |
| `SYNC_OVERLAP_MINUTES` | `5` | 增量同步与上次成功时间重叠的分钟数，避免边界更新遗漏 |
| `GLM_API_KEY` | 空 | GLM API 密钥，仅由服务端读取 |
| `GLM_API_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI SDK 使用的兼容 API 基础地址，不包含 `/chat/completions` |
| `GLM_MODEL` | `glm-5.3-flash` | Issue 分析使用的模型 ID |
| `GLM_REQUEST_TIMEOUT` | `120` | GLM 请求超时时间（秒） |
| `GLM_REASONING_EFFORT` | `high` | 推理强度；Issue 根因分析默认优先保证准确性 |
| `GLM_MAX_OUTPUT_TOKENS` | `16384` | 单次分析最大输出 token 数；为推理过程和最终 JSON 预留空间，实际可用上限取决于模型服务 |
| `GLM_MAX_INPUT_CHARS` | `40000` | 单次分析最多发送的上下文字符数 |
| `GLM_MAX_COMMENTS` | `100` | 单次分析最多读取的 GitHub 评论数 |
| `GLM_LOG_PAYLOADS` | `false` | 是否在日志中记录 GLM 请求和响应正文；排障结束后应关闭 |
| `GLM_LOG_MAX_CHARS` | `20000` | 请求或响应正文在日志中的最大字符数 |
| `AI_BATCH_MAX_ISSUES` | `5000` | 单个批量任务允许包含的最大 Issue 数量 |
| `AI_BATCH_CONCURRENCY` | `3` | 批量分析 Worker 并发数，允许范围为 1～16 |
| `AI_BATCH_MAX_ATTEMPTS` | `3` | 每条 Issue 分析失败后的最大尝试次数 |
| `AI_BATCH_RETRY_DELAY_SECONDS` | `2` | 批量分析失败后重新尝试前的等待秒数 |
| `DB_PATH` | `data/issues.db` | SQLite 文件路径 |
| `PORT` | `8080` | 服务端口 |

内网代理使用自签名证书且暂时无法取得根证书时，可以关闭 GitHub API 的证书校验：

在 `.env` 中设置 `GITHUB_SSL_VERIFY=false`。

此配置仅影响 GitHub 数据同步。关闭校验后代理能够读取或修改 GitHub 返回内容，不应在不可信网络中使用，也不应同时配置高权限 `GITHUB_TOKEN`。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 运行限制

- 只启动一个应用实例和一个 Python 进程。
- 不要使用多 worker 运行，否则每个 worker 都可能启动同步线程。
- 多实例和多人高并发场景需要将 SQLite 替换为 PostgreSQL。
