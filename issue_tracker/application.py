import base64
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "issues.db"
SYNC_LOCK = threading.Lock()

MANUAL_FIELDS = {
    "summary_zh",
    "value_level",
    "source_type",
    "conclusion_status",
    "identification_result",
    "missed_test_reason",
    "supplemental_test",
    "notes",
}

SORT_FIELDS = {
    "number": "number",
    "created": "github_created_at",
    "updated": "github_updated_at",
    "state": "upstream_state",
    "value": "value_level",
}

FALSE_VALUES = {"0", "false", "no", "off"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_env_file(path):
    path = Path(path)
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path}:{line_number} 不是有效的 KEY=VALUE 配置")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def env_flag(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in FALSE_VALUES


def get_connection(app):
    connection = sqlite3.connect(app.config["DB_PATH"], timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_database(app):
    Path(app.config["DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(app) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS issues (
                number INTEGER PRIMARY KEY,
                repository TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                html_url TEXT NOT NULL,
                upstream_state TEXT NOT NULL,
                state_reason TEXT,
                author TEXT,
                author_avatar_url TEXT,
                labels_json TEXT NOT NULL DEFAULT '[]',
                github_created_at TEXT NOT NULL,
                github_updated_at TEXT NOT NULL,
                github_closed_at TEXT,
                comment_count INTEGER NOT NULL DEFAULT 0,
                summary_zh TEXT NOT NULL DEFAULT '',
                value_level TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                conclusion_status TEXT NOT NULL DEFAULT '',
                identification_result TEXT NOT NULL DEFAULT '',
                missed_test_reason TEXT NOT NULL DEFAULT '',
                supplemental_test TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                first_synced_at TEXT NOT NULL,
                last_synced_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_issues_state
                ON issues(upstream_state);
            CREATE INDEX IF NOT EXISTS idx_issues_created
                ON issues(github_created_at);
            CREATE INDEX IF NOT EXISTS idx_issues_updated
                ON issues(github_updated_at);
            CREATE INDEX IF NOT EXISTS idx_issues_identification
                ON issues(identification_result);

            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT NOT NULL DEFAULT 'idle',
                last_attempt_at TEXT,
                last_success_at TEXT,
                last_error TEXT,
                fetched_count INTEGER NOT NULL DEFAULT 0,
                rate_remaining INTEGER,
                rate_limit INTEGER
            );

            INSERT OR IGNORE INTO sync_state(id, status) VALUES (1, 'idle');
            """
        )


def row_to_issue(row, include_body=False):
    issue = dict(row)
    issue["labels"] = json.loads(issue.pop("labels_json") or "[]")
    if not include_body:
        body = issue.pop("body", "")
        issue["body_excerpt"] = " ".join(body.split())[:220]
    return issue


def next_link_url(link_header):
    for part in (link_header or "").split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def github_request(app, url=None, since=None):
    query = {
        "state": "all",
        "sort": "updated",
        "direction": "asc",
        "per_page": app.config["GITHUB_PAGE_SIZE"],
    }
    if since:
        query["since"] = since
    request_parameters = None
    if not url:
        url = f"https://api.github.com/repos/{app.config['GITHUB_REPOSITORY']}/issues"
        request_parameters = query
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "vllm-ascend-issue-tracker",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    if app.config["GITHUB_TOKEN"]:
        headers["Authorization"] = f"Bearer {app.config['GITHUB_TOKEN']}"

    session = app.extensions["github_http"]
    retry_count = app.config["GITHUB_REQUEST_RETRIES"]
    for attempt in range(retry_count + 1):
        response = None
        try:
            response = session.get(
                url,
                params=request_parameters,
                headers=headers,
                timeout=30,
                verify=app.config["GITHUB_SSL_VERIFY"],
            )
            if response.status_code == 403 and response.headers.get(
                "X-RateLimit-Remaining"
            ) == "0":
                reset_at = response.headers.get("X-RateLimit-Reset", "未知")
                token_hint = (
                    "当前 Token 的限额已耗尽"
                    if app.config["GITHUB_TOKEN"]
                    else "请在 .env 中配置 GITHUB_TOKEN 以使用认证额度"
                )
                raise RuntimeError(
                    f"GitHub API 请求限额已耗尽（重置时间戳: {reset_at}）；{token_hint}"
                )
            if response.status_code >= 400:
                detail = response.text[:300]
                if response.status_code not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(
                        f"GitHub API 返回 {response.status_code}: {detail}"
                    )
                response.raise_for_status()

            payload = response.json()
            return payload, {
                "remaining": response.headers.get("X-RateLimit-Remaining"),
                "limit": response.headers.get("X-RateLimit-Limit"),
            }, next_link_url(response.headers.get("Link"))
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RetryError,
            requests.exceptions.JSONDecodeError,
        ) as error:
            request_error = error
        finally:
            if response is not None:
                response.close()

        if attempt >= retry_count:
            raise RuntimeError(
                f"GitHub API 请求重试 {retry_count} 次后仍失败: {request_error}"
            ) from request_error

        delay_seconds = min(2**attempt, 8)
        app.logger.warning(
            "GitHub API request interrupted; retrying in %s seconds (%s/%s): %s",
            delay_seconds,
            attempt + 1,
            retry_count,
            request_error,
        )
        time.sleep(delay_seconds)


def update_sync_state(app, **values):
    if not values:
        return
    assignments = ", ".join(f"{key} = ?" for key in values)
    with get_connection(app) as connection:
        connection.execute(
            f"UPDATE sync_state SET {assignments} WHERE id = 1",
            list(values.values()),
        )


def upsert_issues(app, issues, synced_at):
    records = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        records.append(
            (
                issue["number"],
                app.config["GITHUB_REPOSITORY"],
                issue["title"],
                issue.get("body") or "",
                issue["html_url"],
                issue["state"],
                issue.get("state_reason"),
                (issue.get("user") or {}).get("login"),
                (issue.get("user") or {}).get("avatar_url"),
                json.dumps(
                    [label["name"] for label in issue.get("labels", [])],
                    ensure_ascii=False,
                ),
                issue["created_at"],
                issue["updated_at"],
                issue.get("closed_at"),
                issue.get("comments", 0),
                synced_at,
                synced_at,
            )
        )

    if not records:
        return 0

    with get_connection(app) as connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO issues (
                number, repository, title, body, html_url, upstream_state,
                state_reason, author, author_avatar_url, labels_json,
                github_created_at, github_updated_at, github_closed_at,
                comment_count, first_synced_at, last_synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        connection.executemany(
            """
            UPDATE issues SET
                repository = ?, title = ?, body = ?, html_url = ?,
                upstream_state = ?, state_reason = ?, author = ?,
                author_avatar_url = ?, labels_json = ?, github_created_at = ?,
                github_updated_at = ?, github_closed_at = ?, comment_count = ?,
                last_synced_at = ?
            WHERE number = ?
            """,
            [
                (
                    record[1], record[2], record[3], record[4], record[5],
                    record[6], record[7], record[8], record[9], record[10],
                    record[11], record[12], record[13], record[15], record[0],
                )
                for record in records
            ],
        )
    return len(records)


def perform_sync(app):
    if not SYNC_LOCK.acquire(blocking=False):
        return False

    sync_started = utc_now()
    fetched_count = 0
    last_rate = {"remaining": None, "limit": None}
    try:
        with get_connection(app) as connection:
            state = connection.execute(
                "SELECT last_success_at FROM sync_state WHERE id = 1"
            ).fetchone()
        since = state["last_success_at"] if state else None
        update_sync_state(
            app,
            status="syncing",
            last_attempt_at=sync_started,
            last_error=None,
            fetched_count=0,
        )

        next_url = None
        while True:
            payload, last_rate, next_url = github_request(
                app,
                url=next_url,
                since=since if next_url is None and fetched_count == 0 else None,
            )
            fetched_count += upsert_issues(app, payload, sync_started)
            update_sync_state(app, fetched_count=fetched_count)
            if not next_url:
                break

        update_sync_state(
            app,
            status="idle",
            last_success_at=sync_started,
            last_error=None,
            fetched_count=fetched_count,
            rate_remaining=int(last_rate["remaining"]) if last_rate["remaining"] else None,
            rate_limit=int(last_rate["limit"]) if last_rate["limit"] else None,
        )
        return True
    except Exception as error:
        update_sync_state(app, status="error", last_error=str(error)[:1000])
        app.logger.exception("GitHub issue synchronization failed")
        return False
    finally:
        SYNC_LOCK.release()


def start_sync_thread(app):
    interval_seconds = max(1, app.config["SYNC_INTERVAL_MINUTES"]) * 60

    def loop():
        perform_sync(app)
        while True:
            time.sleep(interval_seconds)
            perform_sync(app)

    threading.Thread(target=loop, name="github-sync", daemon=True).start()


def create_app(test_config=None):
    env_file = Path(os.getenv("ENV_FILE", str(PROJECT_ROOT / ".env")))
    load_env_file(env_file)

    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.extensions["github_http"] = requests.Session()
    app.config.update(
        ENV_FILE=str(env_file),
        DB_PATH=os.getenv("DB_PATH", str(DEFAULT_DB_PATH)),
        GITHUB_REPOSITORY=os.getenv(
            "GITHUB_REPOSITORY", "vllm-project/vllm-ascend"
        ),
        GITHUB_TOKEN=os.getenv("GITHUB_TOKEN", ""),
        GITHUB_SSL_VERIFY=env_flag("GITHUB_SSL_VERIFY", default=True),
        GITHUB_PAGE_SIZE=max(1, min(100, int(os.getenv("GITHUB_PAGE_SIZE", "100")))),
        GITHUB_REQUEST_RETRIES=max(
            0, min(10, int(os.getenv("GITHUB_REQUEST_RETRIES", "3")))
        ),
        APP_USERNAME=os.getenv("APP_USERNAME", "admin"),
        APP_PASSWORD=os.getenv("APP_PASSWORD", "admin"),
        SYNC_INTERVAL_MINUTES=int(os.getenv("SYNC_INTERVAL_MINUTES", "15")),
    )
    if test_config:
        app.config.update(test_config)
    initialize_database(app)

    @app.before_request
    def require_authentication():
        if request.path == "/healthz":
            return None
        authorization = request.headers.get("Authorization", "")
        expected = base64.b64encode(
            f"{app.config['APP_USERNAME']}:{app.config['APP_PASSWORD']}".encode()
        ).decode()
        if authorization != f"Basic {expected}":
            return (
                jsonify({"error": "需要登录"}),
                401,
                {"WWW-Authenticate": 'Basic realm="Ascend Issue Tracker"'},
            )
        return None

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/issues")
    def list_issues():
        page = max(1, request.args.get("page", 1, type=int))
        page_size = min(100, max(10, request.args.get("page_size", 30, type=int)))
        conditions = []
        parameters = []

        query = request.args.get("q", "").strip()
        if query:
            conditions.append("(title LIKE ? OR body LIKE ? OR summary_zh LIKE ?)")
            wildcard = f"%{query}%"
            parameters.extend([wildcard, wildcard, wildcard])

        state = request.args.get("state", "").strip().lower()
        if state in {"open", "closed"}:
            conditions.append("upstream_state = ?")
            parameters.append(state)

        if request.args.get("created") == "last_month":
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace(
                "+00:00", "Z"
            )
            conditions.append("github_created_at >= ?")
            parameters.append(cutoff)

        exact_filters = {
            "identified": "identification_result",
            "value": "value_level",
            "conclusion": "conclusion_status",
            "source": "source_type",
        }
        for argument, column in exact_filters.items():
            value = request.args.get(argument, "").strip()
            if value:
                conditions.append(f"{column} = ?")
                parameters.append(value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sort_column = SORT_FIELDS.get(request.args.get("sort"), "github_created_at")
        direction = "ASC" if request.args.get("direction") == "asc" else "DESC"
        offset = (page - 1) * page_size

        with get_connection(app) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM issues {where_clause}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM issues
                {where_clause}
                ORDER BY {sort_column} {direction}, number DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, page_size, offset],
            ).fetchall()
            counts = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN upstream_state = 'open' THEN 1 ELSE 0 END) AS open,
                       SUM(CASE WHEN upstream_state = 'closed' THEN 1 ELSE 0 END) AS closed,
                       SUM(CASE WHEN identification_result = '确认问题' THEN 1 ELSE 0 END) AS identified
                FROM issues
                """
            ).fetchone()

        return jsonify(
            {
                "items": [row_to_issue(row) for row in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, (total + page_size - 1) // page_size),
                "counts": {key: counts[key] or 0 for key in counts.keys()},
            }
        )

    @app.get("/api/issues/<int:number>")
    def get_issue(number):
        with get_connection(app) as connection:
            row = connection.execute(
                "SELECT * FROM issues WHERE number = ?", (number,)
            ).fetchone()
        if not row:
            return jsonify({"error": "Issue 不存在"}), 404
        return jsonify(row_to_issue(row, include_body=True))

    @app.patch("/api/issues/<int:number>")
    def update_issue(number):
        payload = request.get_json(silent=True) or {}
        updates = {
            key: str(value or "").strip()
            for key, value in payload.items()
            if key in MANUAL_FIELDS
        }
        if not updates:
            return jsonify({"error": "没有可更新的分析字段"}), 400
        if any(len(value) > 20000 for value in updates.values()):
            return jsonify({"error": "字段内容过长"}), 400

        assignments = ", ".join(f"{key} = ?" for key in updates)
        with get_connection(app) as connection:
            cursor = connection.execute(
                f"UPDATE issues SET {assignments} WHERE number = ?",
                [*updates.values(), number],
            )
        if cursor.rowcount == 0:
            return jsonify({"error": "Issue 不存在"}), 404
        return jsonify({"ok": True})

    @app.get("/api/sync/status")
    def sync_status():
        with get_connection(app) as connection:
            row = connection.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        return jsonify(dict(row))

    @app.post("/api/sync")
    def trigger_sync():
        if SYNC_LOCK.locked():
            return jsonify({"ok": True, "status": "syncing"}), 202
        update_sync_state(app, status="queued", last_error=None)
        threading.Thread(
            target=perform_sync, args=(app,), name="manual-github-sync", daemon=True
        ).start()
        return jsonify({"ok": True, "status": "queued"}), 202

    return app


def run():
    app = create_app()
    if app.config["APP_PASSWORD"] == "admin":
        app.logger.warning("APP_PASSWORD is using the default value; change it before deployment.")
    start_sync_thread(app)
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    run()
