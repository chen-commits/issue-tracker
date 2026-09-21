const OPTIONAL_COLUMNS = [
  "state", "labels", "version", "version_support", "created", "result",
  "summary", "value", "missed", "supplemental", "notes", "conclusion",
  "closed_loop", "ai_analysis",
];
const DEFAULT_VISIBLE_COLUMNS = [
  "state", "version", "created", "result", "summary", "missed", "supplemental",
  "notes", "conclusion", "closed_loop",
];
const COLUMN_STORAGE_KEY = "issue-tracker-visible-columns-v7";

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
  currentIssue: null,
  searchTimer: null,
  markdownTimer: null,
  markdownRequest: 0,
  aiSuggestion: null,
  visibleColumns: loadVisibleColumns(),
};

const elements = {
  rows: document.querySelector("#issueRows"),
  empty: document.querySelector("#emptyState"),
  loading: document.querySelector("#loadingMessage"),
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
  analyzeIssueButton: document.querySelector("#analyzeIssueButton"),
  aiSuggestionPanel: document.querySelector("#aiSuggestionPanel"),
  aiSuggestionContent: document.querySelector("#aiSuggestionContent"),
  aiSuggestionMeta: document.querySelector("#aiSuggestionMeta"),
  columnFilters: {
    issue: document.querySelector("#columnIssueFilter"),
    state: document.querySelector("#columnStateFilter"),
    labels: document.querySelector("#columnLabelFilter"),
    version: document.querySelector("#columnVersionFilter"),
    version_support: document.querySelector("#columnVersionSupportFilter"),
    created_from: document.querySelector("#columnCreatedFromFilter"),
    created_to: document.querySelector("#columnCreatedToFilter"),
    summary: document.querySelector("#columnSummaryFilter"),
    value: document.querySelector("#columnValueFilter"),
    missed: document.querySelector("#columnMissedFilter"),
    supplemental: document.querySelector("#columnSupplementalFilter"),
    notes: document.querySelector("#columnNotesFilter"),
    result: document.querySelector("#columnResultFilter"),
    conclusion: document.querySelector("#columnConclusionFilter"),
    closed_loop: document.querySelector("#columnClosedLoopFilter"),
    ai_analysis: document.querySelector("#columnAiAnalysisFilter"),
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

async function exportIssues() {
  const button = document.querySelector("#exportButton");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "导出中…";
  try {
    const params = new URLSearchParams(queryString());
    params.delete("page");
    params.delete("page_size");
    params.set("columns", ["issue", ...state.visibleColumns].join(","));
    const response = await fetch(`/api/issues/export?${params}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `导出失败：${response.status}`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch ? filenameMatch[1] : "vllm-ascend-issues.xlsx";
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
    showToast("Excel 已导出");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
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
    q: elements.columnFilters.issue.value.trim(),
    state: elements.columnFilters.state.value,
    created_from: elements.columnFilters.created_from.value,
    created_to: elements.columnFilters.created_to.value,
    identified: elements.columnFilters.result.value,
    value: elements.columnFilters.value.value,
    conclusion: elements.columnFilters.conclusion.value,
    closed_loop: elements.columnFilters.closed_loop.value,
    version_support: elements.columnFilters.version_support.value,
    label: elements.columnFilters.labels.value.trim(),
    version: elements.columnFilters.version.value.trim(),
    summary: elements.columnFilters.summary.value.trim(),
    missed: elements.columnFilters.missed.value.trim(),
    supplemental: elements.columnFilters.supplemental.value.trim(),
    notes: elements.columnFilters.notes.value.trim(),
    ai_analysis: elements.columnFilters.ai_analysis.value.trim(),
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
  if (type === "closure") {
    const closureClass = value === "是" ? "closure-yes" : "closure-no";
    return `<span class="result-badge ${closureClass}">${escapeHtml(value)}</span>`;
  }
  if (type === "version-support") {
    let supportClass = "support-pending";
    if (value === "当前版本已支持") supportClass = "support-current";
    if (["下个版本支持", "后续版本支持"].includes(value)) supportClass = "support-future";
    if (["不计划支持", "不适用"].includes(value)) supportClass = "support-other";
    return `<span class="result-badge ${supportClass}">${escapeHtml(value)}</span>`;
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

function prepareMarkdownLinks(container = document) {
  container.querySelectorAll(".markdown-body a").forEach((link) => {
    link.target = "_blank";
    link.rel = "noreferrer";
  });
}

function setMarkdownPreview(html) {
  const preview = document.querySelector("#aiAnalysisPreview");
  preview.innerHTML = html || '<span class="muted">暂无内容</span>';
  prepareMarkdownLinks(preview);
}

function scheduleMarkdownPreview() {
  window.clearTimeout(state.markdownTimer);
  const value = document.querySelector("#aiAnalysisInput").value;
  const requestNumber = ++state.markdownRequest;
  if (!value.trim()) {
    setMarkdownPreview("");
    return;
  }
  state.markdownTimer = window.setTimeout(async () => {
    try {
      const result = await api("/api/markdown/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown: value }),
      });
      if (requestNumber === state.markdownRequest) setMarkdownPreview(result.html);
    } catch (error) {
      if (requestNumber === state.markdownRequest) {
        setMarkdownPreview(`<span class="muted">${escapeHtml(error.message)}</span>`);
      }
    }
  }, 250);
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
        <td data-column="version"><div class="cell-text ${issue.affected_version ? "" : "muted"}">${escapeHtml(issue.affected_version || "未填写")}</div></td>
        <td data-column="version_support">${badge(issue.version_support_status, "version-support")}</td>
        <td data-column="created">${formatDate(issue.github_created_at)}</td>
        <td data-column="result">${badge(issue.identification_result, "result")}</td>
        <td data-column="summary"><div class="cell-text ${issue.summary_zh ? "" : "muted"}">${escapeHtml(issue.summary_zh || "未填写")}</div></td>
        <td data-column="value">${badge(issue.value_level, "value")}</td>
        <td data-column="missed"><div class="cell-text ${issue.missed_test_reason ? "" : "muted"}">${escapeHtml(issue.missed_test_reason || "未填写")}</div></td>
        <td data-column="supplemental"><div class="cell-text ${issue.supplemental_test ? "" : "muted"}">${escapeHtml(issue.supplemental_test || "未填写")}</div></td>
        <td data-column="notes"><div class="cell-text ${issue.notes ? "" : "muted"}">${escapeHtml(issue.notes || "未填写")}</div></td>
        <td data-column="conclusion"><div class="cell-text ${issue.conclusion_status ? "" : "muted"}">${escapeHtml(issue.conclusion_status || "未设置")}</div></td>
        <td data-column="closed_loop">${badge(issue.is_closed_loop, "closure")}</td>
        <td data-column="ai_analysis"><div class="markdown-cell markdown-body ${issue.ai_analysis ? "" : "muted"}">${issue.ai_analysis_html || "未填写"}</div></td>
        <td><button class="edit-button" type="button" data-number="${issue.number}">编辑</button></td>
      </tr>`;
  }).join("");
  prepareMarkdownLinks(elements.rows);
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

const AI_SUGGESTION_LABELS = {
  summary_zh: "问题分析",
  identification_result: "识别结果",
  value_level: "价值等级",
  source_type: "问题来源",
  conclusion_status: "结论状态",
  affected_version: "问题版本",
  version_support_status: "版本支持情况",
  missed_test_reason: "漏测原因",
  supplemental_test: "补充测试",
  ai_analysis: "AI 分析结论",
};

function closeAiSuggestion() {
  state.aiSuggestion = null;
  elements.aiSuggestionPanel.hidden = true;
  elements.aiSuggestionContent.innerHTML = "";
  elements.aiSuggestionMeta.textContent = "";
}

function renderAiSuggestion(payload) {
  if (!payload?.suggestion || typeof payload.suggestion !== "object") {
    throw new Error("AI 接口没有返回可展示的分析建议");
  }
  state.aiSuggestion = payload.suggestion;
  const visibleFields = Object.entries(AI_SUGGESTION_LABELS)
    .filter(([field]) => String(payload.suggestion[field] || "").trim());
  const rawSuggestion = document.createElement("textarea");
  rawSuggestion.className = "ai-suggestion-raw";
  rawSuggestion.readOnly = true;
  rawSuggestion.setAttribute("aria-label", "AI 分析建议原文");
  rawSuggestion.value = visibleFields
    .map(([field, label]) => `${label}\n${payload.suggestion[field]}`)
    .join("\n\n");
  elements.aiSuggestionContent.replaceChildren(rawSuggestion);
  if (!visibleFields.length) {
    const empty = document.createElement("div");
    empty.className = "ai-suggestion-empty";
    empty.textContent = "接口返回了建议对象，但其中没有可展示的分析字段。";
    elements.aiSuggestionContent.replaceChildren(empty);
  } else if (payload.ai_analysis_html) {
    const markdownSection = document.createElement("section");
    markdownSection.className = "ai-suggestion-markdown";
    const markdownTitle = document.createElement("div");
    markdownTitle.className = "ai-suggestion-markdown-title";
    markdownTitle.textContent = "AI 分析结论（Markdown 预览）";
    const markdownContent = document.createElement("div");
    markdownContent.className = "markdown-body";
    markdownContent.innerHTML = payload.ai_analysis_html;
    markdownSection.append(markdownTitle, markdownContent);
    elements.aiSuggestionContent.append(markdownSection);
    prepareMarkdownLinks(markdownContent);
  }
  const confidence = Math.round((payload.suggestion.confidence || 0) * 100);
  const tokenText = payload.usage?.total_tokens ? ` · ${payload.usage.total_tokens} tokens` : "";
  const commentText = ` · ${payload.comments_included || 0} 条评论`;
  elements.aiSuggestionMeta.textContent = `${payload.model} · ${visibleFields.length} 个字段 · 置信度 ${confidence}%${commentText}${tokenText}`;
  elements.aiSuggestionPanel.hidden = false;
  const dialogContent = elements.aiSuggestionPanel.closest(".dialog-content");
  if (dialogContent) dialogContent.scrollTo({ top: 0, behavior: "smooth" });
  window.requestAnimationFrame(() => elements.aiSuggestionPanel.focus({ preventScroll: true }));
  showToast("AI 分析建议已生成，请检查后采纳");
  (payload.warnings || []).forEach((warning) => showToast(warning, true));
}

async function analyzeCurrentIssue() {
  if (!state.currentIssue) return;
  const button = elements.analyzeIssueButton;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "分析中…";
  document.querySelector("#saveMessage").textContent = "正在读取评论并请求 GLM…";
  try {
    const payload = await api(`/api/issues/${state.currentIssue.number}/ai-analysis`, {
      method: "POST",
    });
    renderAiSuggestion(payload);
    const result = fillAiSuggestionFields(payload.suggestion, { onlyEmpty: true });
    if (result.aiAnalysisChanged && payload.ai_analysis_html) {
      state.markdownRequest += 1;
      setMarkdownPreview(payload.ai_analysis_html);
    }
    document.querySelector("#saveMessage").textContent =
      `AI 已填写 ${result.filled} 个空字段，保留 ${result.preserved} 个已有字段；检查后再保存`;
  } catch (error) {
    document.querySelector("#saveMessage").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function fillAiSuggestionFields(suggestion, { onlyEmpty = false } = {}) {
  const result = { filled: 0, preserved: 0, aiAnalysisChanged: false };
  if (!suggestion) return result;
  let aiAnalysisChanged = false;
  Object.entries(AI_SUGGESTION_LABELS).forEach(([field]) => {
    const input = elements.form.elements.namedItem(field);
    if (!input || !suggestion[field]) return;
    if (onlyEmpty && String(input.value || "").trim()) {
      result.preserved += 1;
      return;
    }
    input.value = suggestion[field];
    result.filled += 1;
    if (field === "ai_analysis") {
      aiAnalysisChanged = true;
      result.aiAnalysisChanged = true;
    }
  });
  if (aiAnalysisChanged) {
    const aiInput = document.querySelector("#aiAnalysisInput");
    aiInput.dispatchEvent(new Event("input", { bubbles: true }));
  }
  return result;
}

function applyAiSuggestion() {
  if (!state.aiSuggestion) return;
  fillAiSuggestionFields(state.aiSuggestion);
  document.querySelector("#saveMessage").textContent = "AI 建议已填入，请确认后保存";
  showToast("AI 建议已填入表单，尚未保存");
}

async function openEditor(number) {
  try {
    const issue = await api(`/api/issues/${number}`);
    state.currentIssue = issue;
    closeAiSuggestion();
    document.querySelector("#editorNumber").textContent = `#${issue.number}`;
    document.querySelector("#editorTitle").textContent = issue.title;
    document.querySelector("#editorState").textContent = issue.upstream_state === "open" ? "开放" : "关闭";
    document.querySelector("#editorAuthor").textContent = issue.author || "未知作者";
    document.querySelector("#editorLink").href = issue.html_url;
    [...elements.form.elements].forEach((field) => {
      if (field.name && Object.hasOwn(issue, field.name)) field.value = issue[field.name] || "";
    });
    state.markdownRequest += 1;
    setMarkdownPreview(issue.ai_analysis_html);
    document.querySelector("#saveMessage").textContent = "";
    elements.dialog.showModal();
    const dialogContent = elements.dialog.querySelector(".dialog-content");
    if (dialogContent) dialogContent.scrollTop = 0;
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

elements.columnFilters.issue.addEventListener("input", scheduleFilterLoad);
[elements.columnFilters.state, elements.columnFilters.created_from,
  elements.columnFilters.created_to, elements.columnFilters.result,
  elements.columnFilters.value, elements.columnFilters.conclusion,
  elements.columnFilters.closed_loop, elements.columnFilters.version_support]
  .forEach((element) => element.addEventListener("change", resetPageAndLoad));
[elements.columnFilters.labels, elements.columnFilters.summary, elements.columnFilters.missed,
  elements.columnFilters.supplemental, elements.columnFilters.notes,
  elements.columnFilters.version, elements.columnFilters.ai_analysis]
  .forEach((element) => element.addEventListener("input", scheduleFilterLoad));
elements.sort.addEventListener("change", resetPageAndLoad);

document.querySelector("#clearFilters").addEventListener("click", () => {
  elements.sort.value = "created_desc";
  Object.values(elements.columnFilters).forEach((filter) => { filter.value = ""; });
  resetPageAndLoad();
});

elements.previous.addEventListener("click", () => {
  if (state.page > 1) { state.page -= 1; loadIssues(); }
});
elements.next.addEventListener("click", () => {
  if (state.page < state.pages) { state.page += 1; loadIssues(); }
});
document.querySelector("#syncButton").addEventListener("click", triggerSync);
elements.analyzeIssueButton.addEventListener("click", analyzeCurrentIssue);
document.querySelector("#applyAiSuggestion").addEventListener("click", applyAiSuggestion);
document.querySelector("#closeAiSuggestion").addEventListener("click", closeAiSuggestion);
document.querySelector("#exportButton").addEventListener("click", exportIssues);
document.querySelector("#closeEditor").addEventListener("click", () => elements.dialog.close());
document.querySelector("#cancelEditor").addEventListener("click", () => elements.dialog.close());
elements.form.addEventListener("submit", saveEditor);
document.querySelector("#aiAnalysisInput").addEventListener("input", scheduleMarkdownPreview);
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
