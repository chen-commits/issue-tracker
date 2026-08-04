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

## Docker 部署

复制环境变量模板并修改密码：

```bash
cp .env.example .env
```

启动：

```bash
docker compose up -d --build
```

访问 `http://服务器地址:8080`。数据保存在 `./data/issues.db`。

若服务暴露到公网，应通过 Nginx、Caddy 或现有网关提供 HTTPS，不要使用示例密码。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\scripts\run.ps1 -Username admin -Password your-password
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
|-- Dockerfile
|-- docker-compose.yml
`-- requirements.txt
```

## GitHub API 限额

公开仓库可以不配置 Token。首次同步约发出 37 次分页请求，匿名 API 每小时限额较低。如果部署环境经常触发限额，可设置只读 `GITHUB_TOKEN`。

应用仅包含 GitHub `GET /repos/{owner}/{repo}/issues` 请求，不包含写入 GitHub 的代码路径。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `APP_USERNAME` | `admin` | 登录账号 |
| `APP_PASSWORD` | `admin` | 登录密码，部署时必须修改 |
| `GITHUB_REPOSITORY` | `vllm-project/vllm-ascend` | 同步仓库 |
| `GITHUB_TOKEN` | 空 | 可选只读 Token |
| `SYNC_INTERVAL_MINUTES` | `15` | 自动同步间隔 |
| `DB_PATH` | `data/issues.db` | SQLite 文件路径 |
| `PORT` | `8080` | 服务端口 |

## 测试

```bash
python -m unittest discover -s tests -v
```

## 运行限制

- 只启动一个应用实例和一个 Python 进程。
- 不要使用多 worker 运行，否则每个 worker 都可能启动同步线程。
- 多实例和多人高并发场景需要将 SQLite 替换为 PostgreSQL。
