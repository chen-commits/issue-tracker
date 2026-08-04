# vLLM Ascend Issue 分析工具

一个只读同步 GitHub Issue 的轻量内部工具。GitHub 数据通过公共 REST API 获取，测试分析字段仅保存在本地 SQLite 中，不会评论、订阅、修改或关联上游 Issue。

## 功能

- 首次同步全部 `vllm-project/vllm-ascend` Issue
- 每 15 分钟按更新时间增量同步
- 同步 Open/Closed 状态、标题、正文、标签、作者和时间
- 支持最近一个月、状态、识别结果、价值等级和结论状态筛选
- 支持中文简述、漏测原因、补充测试等人工字段
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
python3 app.py
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
|   |-- application.py    # Flask、SQLite 和 GitHub 同步逻辑
|   `-- static/           # HTML、CSS 和 JavaScript
|-- scripts/
|   `-- run.ps1           # Windows 本地启动脚本
|-- tests/                # 自动化测试
|-- data/                 # SQLite 运行数据（自动创建）
|-- app.py                # 应用启动入口
|-- .env.example          # 配置文件模板
`-- requirements.txt
```

## GitHub API 限额

公开仓库可以不配置 Token。首次同步约发出 37 次分页请求，匿名 API 每小时限额较低。如果部署环境经常触发限额，可设置只读 `GITHUB_TOKEN`。

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
| `SYNC_INTERVAL_MINUTES` | `15` | 自动同步间隔 |
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
