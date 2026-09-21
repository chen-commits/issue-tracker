import hashlib
import json
import sqlite3
import threading
import time


BATCH_WAKE_EVENT = threading.Event()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def wake_batch_worker():
    BATCH_WAKE_EVENT.set()


def _connection(app):
    connection = sqlite3.connect(
        app.config["DB_PATH"], timeout=30, factory=ClosingConnection
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_batch_tables(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_batch_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued',
            total_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            cancelled_count INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            last_error TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_number INTEGER NOT NULL REFERENCES issues(number) ON DELETE CASCADE,
            job_id INTEGER REFERENCES ai_batch_jobs(id) ON DELETE SET NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            issue_fingerprint TEXT NOT NULL,
            suggestion_json TEXT NOT NULL,
            ai_analysis_html TEXT NOT NULL DEFAULT '',
            usage_json TEXT NOT NULL DEFAULT '{}',
            comments_included INTEGER NOT NULL DEFAULT 0,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            applied_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ai_runs_issue_created
            ON ai_analysis_runs(issue_number, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_runs_fingerprint
            ON ai_analysis_runs(issue_number, issue_fingerprint);

        CREATE TABLE IF NOT EXISTS ai_batch_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES ai_batch_jobs(id) ON DELETE CASCADE,
            issue_number INTEGER NOT NULL REFERENCES issues(number) ON DELETE CASCADE,
            issue_fingerprint TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            analysis_run_id INTEGER REFERENCES ai_analysis_runs(id) ON DELETE SET NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(job_id, issue_number)
        );

        CREATE INDEX IF NOT EXISTS idx_ai_batch_items_status
            ON ai_batch_items(status, job_id, id);
        """
    )
    item_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(ai_batch_items)")
    }
    if "issue_fingerprint" not in item_columns:
        connection.execute(
            "ALTER TABLE ai_batch_items ADD COLUMN issue_fingerprint TEXT NOT NULL DEFAULT ''"
        )


def issue_fingerprint(issue, model, prompt_version):
    values = [
        issue["repository"],
        str(issue["number"]),
        issue["title"],
        issue["body"],
        issue["github_updated_at"],
        model,
        prompt_version,
    ]
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def create_batch_job(
    app,
    issue_numbers,
    *,
    scope,
    filters,
    skip_existing,
    now,
    prompt_version,
):
    unique_numbers = list(dict.fromkeys(int(number) for number in issue_numbers))
    if not unique_numbers:
        raise ValueError("没有可分析的 Issue")

    placeholders = ",".join("?" for _ in unique_numbers)
    with _connection(app) as connection:
        rows = connection.execute(
            f"SELECT * FROM issues WHERE number IN ({placeholders})",
            unique_numbers,
        ).fetchall()
        issues_by_number = {row["number"]: row for row in rows}
        missing = [number for number in unique_numbers if number not in issues_by_number]
        if missing:
            raise ValueError(f"以下 Issue 不存在：{', '.join(map(str, missing[:10]))}")

        cursor = connection.execute(
            """
            INSERT INTO ai_batch_jobs (
                scope, filters_json, status, total_count, model, prompt_version,
                created_at, updated_at
            ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)
            """,
            (
                scope,
                json.dumps(filters, ensure_ascii=False, sort_keys=True),
                len(unique_numbers),
                app.config["GLM_MODEL"],
                prompt_version,
                now,
                now,
            ),
        )
        job_id = cursor.lastrowid
        skipped_count = 0
        for number in unique_numbers:
            issue = issues_by_number[number]
            fingerprint = issue_fingerprint(
                issue, app.config["GLM_MODEL"], prompt_version
            )
            previous_run = None
            if skip_existing:
                previous_run = connection.execute(
                    """
                    SELECT id FROM ai_analysis_runs
                    WHERE issue_number = ? AND issue_fingerprint = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (number, fingerprint),
                ).fetchone()
            status = "skipped" if previous_run else "queued"
            run_id = previous_run["id"] if previous_run else None
            completed_at = now if previous_run else None
            skipped_count += int(previous_run is not None)
            connection.execute(
                """
                INSERT INTO ai_batch_items (
                    job_id, issue_number, issue_fingerprint, status, analysis_run_id,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, number, fingerprint, status, run_id, now, completed_at),
            )
        if skipped_count == len(unique_numbers):
            connection.execute(
                """
                UPDATE ai_batch_jobs
                SET status = 'completed', skipped_count = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (skipped_count, now, now, job_id),
            )
        elif skipped_count:
            connection.execute(
                "UPDATE ai_batch_jobs SET skipped_count = ? WHERE id = ?",
                (skipped_count, job_id),
            )
    BATCH_WAKE_EVENT.set()
    return job_id


def _job_payload(connection, job_id, item_limit=20):
    job = connection.execute(
        "SELECT * FROM ai_batch_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if not job:
        return None
    payload = dict(job)
    payload["filters"] = json.loads(payload.pop("filters_json") or "{}")
    payload["processed_count"] = (
        payload["success_count"]
        + payload["failure_count"]
        + payload["skipped_count"]
        + payload["cancelled_count"]
    )
    items = connection.execute(
        """
        SELECT item.issue_number, item.status, item.attempt_count, item.error,
               item.analysis_run_id, item.completed_at, issues.title
        FROM ai_batch_items AS item
        JOIN issues ON issues.number = item.issue_number
        WHERE item.job_id = ?
        ORDER BY item.id DESC LIMIT ?
        """,
        (job_id, item_limit),
    ).fetchall()
    payload["items"] = [dict(item) for item in items]
    return payload


def get_batch_job(app, job_id, item_limit=20):
    with _connection(app) as connection:
        return _job_payload(connection, job_id, item_limit)


def get_latest_batch_job(app):
    with _connection(app) as connection:
        row = connection.execute(
            """
            SELECT id FROM ai_batch_jobs
            ORDER BY CASE WHEN status IN ('queued', 'running', 'paused') THEN 0 ELSE 1 END, id DESC
            LIMIT 1
            """
        ).fetchone()
        return _job_payload(connection, row["id"]) if row else None


def get_latest_suggestion(app, issue_number):
    with _connection(app) as connection:
        row = connection.execute(
            """
            SELECT * FROM ai_analysis_runs
            WHERE issue_number = ?
            ORDER BY id DESC LIMIT 1
            """,
            (issue_number,),
        ).fetchone()
    if not row:
        return None
    return {
        "run_id": row["id"],
        "suggestion": json.loads(row["suggestion_json"]),
        "ai_analysis_html": row["ai_analysis_html"],
        "usage": json.loads(row["usage_json"] or "{}"),
        "comments_included": row["comments_included"],
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "analyzed_at": row["created_at"],
        "applied_at": row["applied_at"],
    }


def mark_run_applied(connection, issue_number, run_id, applied_at):
    connection.execute(
        """
        UPDATE ai_analysis_runs SET applied_at = ?
        WHERE id = ? AND issue_number = ?
        """,
        (applied_at, run_id, issue_number),
    )


def cancel_batch_job(app, job_id, now):
    with _connection(app) as connection:
        job = connection.execute(
            "SELECT status FROM ai_batch_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not job:
            return None
        if job["status"] not in {"queued", "running", "paused"}:
            return _job_payload(connection, job_id)
        connection.execute(
            """
            UPDATE ai_batch_items
            SET status = 'cancelled', completed_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (now, job_id),
        )
        connection.execute(
            """
            UPDATE ai_batch_jobs SET status = 'cancelled', completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )
        _refresh_job_counts(connection, job_id, now, preserve_status=True)
        return _job_payload(connection, job_id)


def recover_interrupted_batches(app, now):
    with _connection(app) as connection:
        connection.execute(
            """
            UPDATE ai_batch_items
            SET status = 'cancelled', completed_at = ?
            WHERE status = 'running' AND job_id IN (
                SELECT id FROM ai_batch_jobs WHERE status = 'cancelled'
            )
            """,
            (now,),
        )
        connection.execute(
            """
            UPDATE ai_batch_items
            SET status = 'queued', started_at = NULL,
                error = CASE WHEN error IS NULL THEN '服务重启后重新排队' ELSE error END
            WHERE status = 'running' AND job_id IN (
                SELECT id FROM ai_batch_jobs WHERE status = 'running'
            )
            """
        )
        connection.execute(
            """
            UPDATE ai_batch_jobs SET status = 'queued', updated_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )


def _refresh_job_counts(connection, job_id, now, preserve_status=False):
    counts = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
            SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) AS pending
        FROM ai_batch_items WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    values = [counts[key] or 0 for key in counts.keys()]
    succeeded, failed, skipped, cancelled, pending = values
    connection.execute(
        """
        UPDATE ai_batch_jobs
        SET success_count = ?, failure_count = ?, skipped_count = ?,
            cancelled_count = ?, updated_at = ?
        WHERE id = ?
        """,
        (succeeded, failed, skipped, cancelled, now, job_id),
    )
    if not preserve_status and pending == 0:
        connection.execute(
            """
            UPDATE ai_batch_jobs SET status = 'completed', completed_at = ?, updated_at = ?
            WHERE id = ? AND status != 'cancelled'
            """,
            (now, now, job_id),
        )


def _is_configuration_error(error):
    message = str(error)
    return any(
        marker in message
        for marker in (
            "GLM API 返回 400",
            "GLM API 返回 401",
            "GLM API 返回 403",
            "GLM API 返回 404",
            "GLM API 返回 422",
            "尚未配置 GLM_API_KEY",
        )
    )


def process_next_batch_item(app, analyzer, now_factory):
    with _connection(app) as connection:
        connection.execute("BEGIN IMMEDIATE")
        item = connection.execute(
            """
            SELECT item.*, job.model, job.prompt_version
            FROM ai_batch_items AS item
            JOIN ai_batch_jobs AS job ON job.id = item.job_id
            WHERE item.status = 'queued' AND job.status IN ('queued', 'running')
            ORDER BY item.id LIMIT 1
            """
        ).fetchone()
        if not item:
            return False
        now = now_factory()
        connection.execute(
            """
            UPDATE ai_batch_items
            SET status = 'running', attempt_count = attempt_count + 1,
                started_at = ?, error = NULL
            WHERE id = ?
            """,
            (now, item["id"]),
        )
        connection.execute(
            """
            UPDATE ai_batch_jobs
            SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ?
            """,
            (now, now, item["job_id"]),
        )

    try:
        result = analyzer(app, item["issue_number"])
        with _connection(app) as connection:
            completed_at = now_factory()
            cursor = connection.execute(
                """
                INSERT INTO ai_analysis_runs (
                    issue_number, job_id, model, prompt_version, issue_fingerprint,
                    suggestion_json, ai_analysis_html, usage_json, comments_included,
                    warnings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["issue_number"],
                    item["job_id"],
                    result["model"],
                    result["prompt_version"],
                    item["issue_fingerprint"],
                    json.dumps(result["suggestion"], ensure_ascii=False),
                    result["ai_analysis_html"],
                    json.dumps(result.get("usage") or {}, ensure_ascii=False),
                    result.get("comments_included", 0),
                    json.dumps(result.get("warnings") or [], ensure_ascii=False),
                    completed_at,
                ),
            )
            connection.execute(
                """
                UPDATE ai_batch_items
                SET status = 'succeeded', analysis_run_id = ?, completed_at = ?, error = NULL
                WHERE id = ?
                """,
                (cursor.lastrowid, completed_at, item["id"]),
            )
            _refresh_job_counts(connection, item["job_id"], completed_at)
    except Exception as error:  # Keep one bad Issue from terminating the worker.
        failed_at = now_factory()
        attempts = item["attempt_count"] + 1
        max_attempts = app.config["AI_BATCH_MAX_ATTEMPTS"]
        configuration_error = _is_configuration_error(error)
        next_status = (
            "queued" if attempts < max_attempts and not configuration_error else "failed"
        )
        with _connection(app) as connection:
            connection.execute(
                """
                UPDATE ai_batch_items
                SET status = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    next_status,
                    str(error)[:2000],
                    failed_at if next_status == "failed" else None,
                    item["id"],
                ),
            )
            connection.execute(
                "UPDATE ai_batch_jobs SET last_error = ?, updated_at = ? WHERE id = ?",
                (str(error)[:2000], failed_at, item["job_id"]),
            )
            _refresh_job_counts(connection, item["job_id"], failed_at)
            if configuration_error:
                connection.execute(
                    """
                    UPDATE ai_batch_jobs SET status = 'paused', updated_at = ?
                    WHERE id = ? AND status != 'cancelled'
                    """,
                    (failed_at, item["job_id"]),
                )
        app.logger.warning(
            "Batch AI analysis failed job=%s issue=#%s attempt=%s/%s: %s",
            item["job_id"],
            item["issue_number"],
            attempts,
            max_attempts,
            error,
        )
        if next_status == "queued":
            time.sleep(app.config["AI_BATCH_RETRY_DELAY_SECONDS"])
    return True


def start_batch_worker(app, analyzer, now_factory):
    recover_interrupted_batches(app, now_factory())

    def loop():
        while True:
            try:
                processed = process_next_batch_item(app, analyzer, now_factory)
            except Exception:
                app.logger.exception("Batch AI worker failed while claiming an item")
                processed = False
            if not processed:
                BATCH_WAKE_EVENT.wait(timeout=2)
                BATCH_WAKE_EVENT.clear()

    threads = []
    concurrency = app.config["AI_BATCH_CONCURRENCY"]
    for worker_number in range(1, concurrency + 1):
        thread = threading.Thread(
            target=loop,
            name=f"ai-batch-worker-{worker_number}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    app.logger.warning("AI batch worker started concurrency=%s", concurrency)
    return threads
