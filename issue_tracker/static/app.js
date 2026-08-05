const OPTIONAL_COLUMNS = [
  "state", "labels", "created", "summary", "value", "missed",
  "supplemental", "notes", "result", "conclusion",
];
const DEFAULT_VISIBLE_COLUMNS = [
  "state", "labels", "created", "missed", "supplemental", "notes",
  "result", "conclusion",
];
const COLUMN_STORAGE_KEY = "issue-tracker-visible-columns-v2";

function loadVisibleColumns() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(COLUMN_STORAGE_KEY));
    if (Array.isArray(saved)) {
      return OPTIONAL_COLUMNS.filter((column) => saved.includes(column));
    }
  } catch (error) {
    // Fall back to the complete column set when browser storage is unavailable.
  }
  return [...DEFAULT_VISIBLE_COLUMNS];
}

const state = {
  page: 1,
  pages: 1,
  selectedState: "",
  currentIssue: null,
  searchTimer: null,
  visibleColumns: loadVisibleColumns(),
};

const elements = {
  rows: document.querySelector("#issueRows"),
  empty: document.querySelector("#emptyState"),
  loading: document.querySelector("#loadingMessage"),
  search: document.querySelector("#searchInput"),
  created: document.querySelector("#createdFilter"),
  identified: document.querySelector("#identifiedFilter"),
  value: document.querySelector("#valueFilter"),
  conclusion: document.querySelector("#conclusionFilter"),
  sort: document.querySelector("#sortSelect"),
  previous: document.querySelector("#previousPage"),
  next: document.querySelector("#nextPage"),
  pageText: document.querySelector("#pageText"),
  dialog: document.querySelector("#editorDialog"),
  form: document.querySelector("#editorForm"),
  toast: document.querySelector("#toast"),
  table: document.querySelector("#issueTable"),
  columnDialog: document.querySelector("#columnDialog"),
  columnForm: document.querySelector("#columnForm"),
  columnFilters: {
    issue: document.querySelector("#columnIssueFilter"),
    state: document.querySelector("#columnStateFilter"),
    labels: document.querySelector("#columnLabelFilter"),
    created: document.querySelector("#columnCreatedFilter"),
    summary: document.querySelector("#columnSummaryFilter"),
    value: document.querySelector("#columnValueFilter"),
    missed: document.querySelector("#columnMissedFilter"),
    supplemental: document.querySelector("#columnSupplementalFilter"),
    notes: document.querySelector("#columnNotesFilter"),
    result: document.querySelector("#columnResultFilter"),
    conclusion: document.querySelector("#columnConclusionFilter"),
  },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function formatDateTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function showToast(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 3200);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return payload;
}

function queryString() {
  const [sort, direction] = elements.sort.value.split("_");
  const params = new URLSearchParams({
    page: state.page,
    page_size: 30,
    sort,
    direction,
  });
  const filters = {
    q: elements.search.value.trim(),
    state: state.selectedState,
    created: elements.created.value,
    identified: elements.identified.value,
    value: elements.value.value,
    conclusion: elements.conclusion.value,
    label: elements.columnFilters.labels.value.trim(),
    summary: elements.columnFilters.summary.value.trim(),
    missed: elements.columnFilters.missed.value.trim(),
    supplemental: elements.columnFilters.supplemental.value.trim(),
    notes: elements.columnFilters.notes.value.trim(),
  };
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params.toString();
}

function badge(value, type) {
  if (!value) return '<span class="muted">未设置</span>';
  let className = "result-other";
  if (type === "value") {
    className = value === "高" ? "value-high" : value === "中" ? "value-medium" : "value-low";
    return `<span class="value-badge ${className}">${escapeHtml(value)}</span>`;
  }
  if (type === "result" && value === "确认问题") className = "result-confirmed";
  return `<span class="result-badge ${className}">${escapeHtml(value)}</span>`;
}

function applyColumnVisibility() {
  document.querySelectorAll("[data-column]").forEach((element) => {
    element.hidden = !state.visibleColumns.includes(element.dataset.column);
  });
  elements.table.style.minWidth = `${560 + state.visibleColumns.length * 92}px`;
}

function openColumnSettings() {
  elements.columnForm.querySelectorAll('input[name="column"]').forEach((input) => {
    input.checked = state.visibleColumns.includes(input.value);
  });
  elements.columnDialog.showModal();
}

function saveColumnSettings(event) {
  event.preventDefault();
  state.visibleColumns = [...new FormData(elements.columnForm).getAll("column")];
  OPTIONAL_COLUMNS.forEach((column) => {
    if (state.visibleColumns.includes(column)) return;
    const filter = elements.columnFilters[column];
    if (filter) filter.value = "";
  });
  if (!state.visibleColumns.includes("state")) setStateFilter("");
  if (!state.visibleColumns.includes("created")) elements.created.value = "";
  if (!state.visibleColumns.includes("value")) elements.value.value = "";
  if (!state.visibleColumns.includes("result")) elements.identified.value = "";
  if (!state.visibleColumns.includes("conclusion")) elements.conclusion.value = "";
  try {
    window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(state.visibleColumns));
  } catch (error) {
    showToast("列设置仅在当前页面生效", true);
  }
  applyColumnVisibility();
  elements.columnDialog.close();
  resetPageAndLoad();
}

function renderRows(items) {
  elements.rows.innerHTML = items.map((issue) => {
    const labels = issue.labels.length
      ? issue.labels.slice(0, 4).map((label) => `<span class="label-chip">${escapeHtml(label)}</span>`).join("")
      : '<span class="muted">无</span>';
    const stateText = issue.upstream_state === "open" ? "开放" : "关闭";
    const stateClass = issue.upstream_state === "open" ? "state-open" : "state-closed";
    const avatar = issue.author_avatar_url
      ? `<img class="avatar" src="${escapeHtml(issue.author_avatar_url)}" alt="" loading="lazy">`
      : '<span class="avatar" aria-hidden="true"></span>';
    return `
      <tr>
        <td>
          <div class="issue-cell">
            ${avatar}
            <div>
              <a class="issue-title" href="${escapeHtml(issue.html_url)}" target="_blank" rel="noreferrer">${escapeHtml(issue.title)}</a>
              <div class="issue-meta">#${issue.number} · ${escapeHtml(issue.author || "未知作者")} · ${issue.comment_count} 条评论</div>
            </div>
          </div>
        </td>
        <td data-column="state"><span class="state-badge ${stateClass}">${stateText}</span></td>
        <td data-column="labels"><div class="labels">${labels}</div></td>
        <td data-column="created">${formatDate(issue.github_created_at)}</td>
        <td data-column="summary"><div class="cell-text ${issue.summary_zh ? "" : "muted"}">${escapeHtml(issue.summary_zh || "未填写")}</div></td>
        <td data-column="value">${badge(issue.value_level, "value")}</td>
        <td data-column="missed"><div class="cell-text ${issue.missed_test_reason ? "" : "muted"}">${escapeHtml(issue.missed_test_reason || "未填写")}</div></td>
        <td data-column="supplemental"><div class="cell-text ${issue.supplemental_test ? "" : "muted"}">${escapeHtml(issue.supplemental_test || "未填写")}</div></td>
        <td data-column="notes"><div class="cell-text ${issue.notes ? "" : "muted"}">${escapeHtml(issue.notes || "未填写")}</div></td>
        <td data-column="result">${badge(issue.identification_result, "result")}</td>
        <td data-column="conclusion"><div class="cell-text ${issue.conclusion_status ? "" : "muted"}">${escapeHtml(issue.conclusion_status || "未设置")}</div></td>
        <td><button class="edit-button" type="button" data-number="${issue.number}">编辑</button></td>
      </tr>`;
  }).join("");
  applyColumnVisibility();
  elements.empty.hidden = items.length !== 0;
  document.querySelectorAll(".edit-button").forEach((button) => {
    button.addEventListener("click", () => openEditor(button.dataset.number));
  });
}

async function loadIssues() {
  elements.loading.textContent = "正在读取 Issue…";
  try {
    const payload = await api(`/api/issues?${queryString()}`);
    state.pages = payload.pages;
    renderRows(payload.items);
    document.querySelector("#totalCount").textContent = payload.counts.total;
    document.querySelector("#openCount").textContent = payload.counts.open;
    document.querySelector("#closedCount").textContent = payload.counts.closed;
    document.querySelector("#identifiedCount").textContent = payload.counts.identified;
    document.querySelector("#filteredCount").textContent = payload.total;
    elements.pageText.textContent = `第 ${payload.page} / ${payload.pages} 页`;
    elements.previous.disabled = payload.page <= 1;
    elements.next.disabled = payload.page >= payload.pages;
    elements.loading.textContent = payload.total ? `显示 ${payload.items.length} 条` : "没有匹配结果";
  } catch (error) {
    elements.loading.textContent = "读取失败";
    showToast(error.message, true);
  }
}

async function loadSyncStatus() {
  try {
    const status = await api("/api/sync/status");
    const dot = document.querySelector("#syncDot");
    const text = document.querySelector("#syncText");
    const button = document.querySelector("#syncButton");
    dot.className = "status-dot";
    if (["syncing", "queued"].includes(status.status)) {
      dot.classList.add("busy");
      text.textContent = `同步中 · ${status.fetched_count || 0} 条`;
      button.disabled = true;
    } else if (status.status === "error") {
      dot.classList.add("error");
      text.textContent = "同步失败";
      button.disabled = false;
    } else {
      dot.classList.add("ok");
      text.textContent = status.last_success_at
        ? `已同步 ${formatDateTime(status.last_success_at)}`
        : "等待首次同步";
      button.disabled = false;
    }
    if (status.status === "error" && status.last_error) {
      text.title = status.last_error;
    }
  } catch (error) {
    document.querySelector("#syncText").textContent = "状态读取失败";
  }
}

async function triggerSync() {
  const button = document.querySelector("#syncButton");
  button.disabled = true;
  try {
    await api("/api/sync", { method: "POST" });
    showToast("同步任务已启动");
    await loadSyncStatus();
  } catch (error) {
    showToast(error.message, true);
    button.disabled = false;
  }
}

async function openEditor(number) {
  try {
    const issue = await api(`/api/issues/${number}`);
    state.currentIssue = issue;
    document.querySelector("#editorNumber").textContent = `#${issue.number}`;
    document.querySelector("#editorTitle").textContent = issue.title;
    document.querySelector("#editorState").textContent = issue.upstream_state === "open" ? "开放" : "关闭";
    document.querySelector("#editorAuthor").textContent = issue.author || "未知作者";
    document.querySelector("#editorLink").href = issue.html_url;
    [...elements.form.elements].forEach((field) => {
      if (field.name && Object.hasOwn(issue, field.name)) field.value = issue[field.name] || "";
    });
    document.querySelector("#saveMessage").textContent = "";
    elements.dialog.showModal();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveEditor(event) {
  event.preventDefault();
  if (!state.currentIssue) return;
  const payload = Object.fromEntries(new FormData(elements.form).entries());
  const message = document.querySelector("#saveMessage");
  message.textContent = "正在保存…";
  try {
    await api(`/api/issues/${state.currentIssue.number}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    elements.dialog.close();
    showToast("分析结果已保存");
    await loadIssues();
  } catch (error) {
    message.textContent = error.message;
  }
}

function resetPageAndLoad() {
  state.page = 1;
  loadIssues();
}

function scheduleFilterLoad() {
  window.clearTimeout(state.searchTimer);
  state.searchTimer = window.setTimeout(resetPageAndLoad, 300);
}

function setStateFilter(value) {
  state.selectedState = value;
  elements.columnFilters.state.value = value;
  document.querySelectorAll("#stateFilter button").forEach((button) => {
    button.classList.toggle("active", button.dataset.value === value);
  });
}

function bindSelectPair(primary, columnFilter) {
  primary.addEventListener("change", () => {
    columnFilter.value = primary.value;
    resetPageAndLoad();
  });
  columnFilter.addEventListener("change", () => {
    primary.value = columnFilter.value;
    resetPageAndLoad();
  });
}

document.querySelector("#stateFilter").addEventListener("click", (event) => {
  if (!event.target.matches("button")) return;
  setStateFilter(event.target.dataset.value);
  resetPageAndLoad();
});

elements.search.addEventListener("input", () => {
  elements.columnFilters.issue.value = elements.search.value;
  scheduleFilterLoad();
});
elements.columnFilters.issue.addEventListener("input", () => {
  elements.search.value = elements.columnFilters.issue.value;
  scheduleFilterLoad();
});
elements.columnFilters.state.addEventListener("change", () => {
  setStateFilter(elements.columnFilters.state.value);
  resetPageAndLoad();
});
bindSelectPair(elements.created, elements.columnFilters.created);
bindSelectPair(elements.identified, elements.columnFilters.result);
bindSelectPair(elements.value, elements.columnFilters.value);
bindSelectPair(elements.conclusion, elements.columnFilters.conclusion);
[elements.columnFilters.labels, elements.columnFilters.summary, elements.columnFilters.missed,
  elements.columnFilters.supplemental, elements.columnFilters.notes]
  .forEach((element) => element.addEventListener("input", scheduleFilterLoad));
elements.sort.addEventListener("change", resetPageAndLoad);

document.querySelector("#clearFilters").addEventListener("click", () => {
  elements.search.value = "";
  elements.created.value = "";
  elements.identified.value = "";
  elements.value.value = "";
  elements.conclusion.value = "";
  elements.sort.value = "created_desc";
  Object.values(elements.columnFilters).forEach((filter) => { filter.value = ""; });
  setStateFilter("");
  resetPageAndLoad();
});

elements.previous.addEventListener("click", () => {
  if (state.page > 1) { state.page -= 1; loadIssues(); }
});
elements.next.addEventListener("click", () => {
  if (state.page < state.pages) { state.page += 1; loadIssues(); }
});
document.querySelector("#syncButton").addEventListener("click", triggerSync);
document.querySelector("#closeEditor").addEventListener("click", () => elements.dialog.close());
document.querySelector("#cancelEditor").addEventListener("click", () => elements.dialog.close());
elements.form.addEventListener("submit", saveEditor);
document.querySelector("#columnSettingsButton").addEventListener("click", openColumnSettings);
document.querySelector("#closeColumnDialog").addEventListener("click", () => elements.columnDialog.close());
document.querySelector("#cancelColumnDialog").addEventListener("click", () => elements.columnDialog.close());
document.querySelector("#showAllColumns").addEventListener("click", () => {
  elements.columnForm.querySelectorAll('input[name="column"]').forEach((input) => {
    input.checked = true;
  });
});
elements.columnForm.addEventListener("submit", saveColumnSettings);

applyColumnVisibility();
loadIssues();
loadSyncStatus();
window.setInterval(loadSyncStatus, 5000);
