#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-${PROJECT_DIR}/logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/issue-tracker.log}"
PID_FILE="${PID_FILE:-${PROJECT_DIR}/issue-tracker.pid}"

if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"
else
    PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

if [[ -f "${PID_FILE}" ]]; then
    EXISTING_PID="$(cat "${PID_FILE}")"
    if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" 2>/dev/null; then
        echo "Issue Tracker is already running (PID ${EXISTING_PID})."
        echo "Log: ${LOG_FILE}"
        exit 0
    fi
    rm -f "${PID_FILE}"
fi

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}"

nohup "${PYTHON_BIN}" app.py >>"${LOG_FILE}" 2>&1 &
APP_PID=$!
echo "${APP_PID}" >"${PID_FILE}"

sleep 1
if ! kill -0 "${APP_PID}" 2>/dev/null; then
    echo "Issue Tracker failed to start. Check ${LOG_FILE}." >&2
    rm -f "${PID_FILE}"
    exit 1
fi

echo "Issue Tracker started (PID ${APP_PID})."
echo "Log: ${LOG_FILE}"
