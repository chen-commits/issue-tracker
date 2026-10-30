function buildTriageReviewPlan(basePlan, edits, preserveExisting) {
  if (!basePlan) return [];
  const plan = new Map(basePlan.map((item) => [item.number, item]));
  edits.forEach((item, number) => {
    if (item.result === item.previous_result) plan.delete(number);
    else plan.set(number, item);
  });
  return [...plan.values()].filter((item) => !preserveExisting || !item.previous_result);
}

if (typeof module !== "undefined" && module.exports) module.exports = { buildTriageReviewPlan };

if (typeof document !== "undefined") (() => {
  const dialog = document.querySelector("#triageReviewDialog");
  const form = document.querySelector("#triageReviewForm");
  const rows = document.querySelector("#triageReviewRows");
  const message = document.querySelector("#triageReviewMessage");
  const progress = document.querySelector("#triageReviewProgress");
  const startButton = document.querySelector("#startTriageReview");
  const applyButton = document.querySelector("#applyTriageReview");
  const preserve = document.querySelector("#triageReviewPreserve");
  const choices = ["确认问题", "非问题", "待分析"];
  let session = 0, requestId = 0, page = 1, pages = 1, jobId = null, timer = null;
  let numbers = [], pageItems = [], basePlan = null, planSignature = null;
  let edits = new Map(), saving = false, creating = false, terminal = false;

  function plannedItems() {
    return buildTriageReviewPlan(basePlan, edits, preserve.checked);
  }

  function updateControls() {
    const count = plannedItems().length;
    applyButton.disabled = saving || !terminal || !basePlan || count === 0;
    applyButton.textContent = basePlan ? `一键填写 ${count} 条识别结果` : "一键填写识别结果";
    startButton.disabled = creating || numbers.length === 0;
    document.querySelector("#triageReviewPrevious").disabled = saving || page <= 1;
    document.querySelector("#triageReviewNext").disabled = saving || page >= pages;
    document.querySelector("#triageReviewPage").textContent = `第 ${page} / ${pages} 页`;
  }

  function renderItems(items) {
    pageItems = items;
    rows.replaceChildren();
    items.forEach((item) => {
      const row = document.createElement("tr");
      const issue = document.createElement("td");
      const link = document.createElement("a");
      link.textContent = `#${item.number} ${item.title}`;
      link.href = /^https?:\/\//i.test(item.html_url) ? item.html_url : "#";
      link.target = "_blank";
      link.rel = "noreferrer";
      issue.append(link);
      const result = document.createElement("td");
      if (item.result) {
        const select = document.createElement("select");
        select.setAttribute("aria-label", `Issue #${item.number} 识别结果`);
        choices.forEach((choice) => {
          const option = document.createElement("option");
          option.value = choice;
          option.textContent = choice;
          select.append(option);
        });
        select.value = preserve.checked && item.current_result ? item.current_result : edits.get(item.number)?.result || item.result;
        select.disabled = saving || !terminal || (preserve.checked && !!item.current_result);
        select.addEventListener("change", () => {
          if (select.value === item.result) edits.delete(item.number);
          else edits.set(item.number, {
            number: item.number, result: select.value, previous_result: item.current_result,
            fingerprint: item.fingerprint, batch_id: item.batch_id, batch_fingerprint: item.batch_fingerprint,
          });
          updateControls();
        });
        result.append(select);
      } else result.textContent = "—";
      if (item.current_result) {
        const existing = document.createElement("small");
        existing.textContent = `已有：${item.current_result}${preserve.checked ? "（保留）" : ""}`;
        result.append(existing);
      }
      const reason = document.createElement("td");
      reason.textContent = preserve.checked && item.current_result && item.result && item.current_result !== item.result
        ? `AI 建议：${item.result}。${item.reason}` : item.reason;
      row.append(issue, result, reason);
      rows.append(row);
    });
    if (!items.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 3;
      cell.textContent = "当前范围没有 Issue";
      row.append(cell);
      rows.append(row);
    }
    updateControls();
  }

  async function loadDraft(resetScope = false) {
    const currentSession = session, currentRequest = ++requestId;
    if (resetScope) { numbers = []; page = pages = 1; renderItems([]); }
    progress.textContent = "正在读取 Issue 列表…";
    startButton.disabled = true;
    const scope = form.querySelector('input[name="scope"]:checked')?.value;
    try {
      const result = await api("/api/ai-triage/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(numbers.length ? { scope: "selected", issue_numbers: numbers, page }
          : { scope, issue_numbers: [...state.selectedIssues], filters: currentFilterPayload(), page }),
      });
      if (currentSession !== session || currentRequest !== requestId || !dialog.open) return;
      numbers = result.issue_numbers;
      page = result.page;
      pages = result.pages;
      progress.textContent = `本次共 ${result.total} 条，点击“开始初筛”后显示结果和理由。`;
      renderItems(result.items);
    } catch (error) {
      if (currentSession !== session || currentRequest !== requestId) return;
      message.textContent = error.message;
      progress.textContent = "无法读取初筛列表";
    }
  }

  async function loadReview() {
    const currentSession = session, currentRequest = ++requestId;
    window.clearTimeout(timer);
    try {
      const result = await api(`/api/ai-batches/${jobId}/triage-review?page=${page}`);
      if (currentSession !== session || currentRequest !== requestId || !dialog.open) return;
      const job = result.job;
      page = result.page;
      pages = result.pages;
      terminal = !["queued", "running"].includes(job.status);
      const status = { queued: "等待初筛", running: "初筛中", completed: "初筛完成", paused: "初筛已暂停", cancelled: "初筛已取消" }[job.status] || job.status;
      progress.textContent = `${status} · 已处理 ${job.processed_count}/${job.total_count} 条${job.failure_count ? ` · 失败 ${job.failure_count} 条` : ""}`;
      document.querySelector("#triageReviewTitle").textContent = `批量初筛 · #${job.id}`;
      renderBatchStatus(job);
      renderItems(result.items);
      const signature = `${job.id}:${job.processed_count}:${job.status}`;
      if (terminal && signature !== planSignature) {
        basePlan = null;
        updateControls();
        const preview = await api("/api/issues/identification/preview", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope: "batch", batch_id: jobId, result: "ai_suggestion", skip_existing: false }),
        });
        if (currentSession !== session || currentRequest !== requestId || !dialog.open) return;
        basePlan = preview.items;
        planSignature = signature;
        message.textContent = `检查结果，有误可修改，然后一键填写。${preview.unavailable_skipped ? ` ${preview.unavailable_skipped} 条无可用结果，不会填写。` : ""}`;
        updateControls();
      }
      if (!terminal) timer = window.setTimeout(loadReview, 3000);
    } catch (error) {
      if (currentSession !== session || currentRequest !== requestId || !dialog.open) return;
      message.textContent = `读取失败，正在重试：${error.message}`;
      timer = window.setTimeout(loadReview, 3000);
    }
  }

  function reset() {
    session += 1;
    requestId += 1;
    window.clearTimeout(timer);
    page = pages = 1;
    jobId = null;
    numbers = [];
    edits = new Map();
    basePlan = planSignature = null;
    terminal = saving = creating = false;
    form.reset();
    rows.replaceChildren();
    message.textContent = "";
    document.querySelector("#triageReviewTitle").textContent = "批量初筛";
    startButton.hidden = false;
    applyButton.hidden = true;
    document.querySelector("#triageReviewScope").hidden = false;
    updateControls();
  }

  window.triageReview = {
    open() {
      reset();
      const selected = form.querySelector('input[value="selected"]');
      selected.disabled = !state.selectedIssues.size;
      selected.checked = !!state.selectedIssues.size;
      const filtered = form.querySelector('input[value="filtered"]');
      filtered.disabled = false;
      filtered.checked = !selected.checked;
      document.querySelector("#triageReviewSelected").textContent = `已选 ${state.selectedIssues.size} 条`;
      document.querySelector("#triageReviewFiltered").textContent = `当前筛选 ${state.filteredTotal} 条`;
      dialog.showModal();
      loadDraft(true);
    },
    openBatch(id) {
      reset();
      jobId = id;
      document.querySelector("#triageReviewScope").hidden = true;
      startButton.hidden = true;
      applyButton.hidden = false;
      dialog.showModal();
      loadReview();
    },
  };

  startButton.addEventListener("click", async () => {
    if (creating || !numbers.length) return;
    creating = true;
    updateControls();
    form.querySelectorAll('input[name="scope"]').forEach((input) => { input.disabled = true; });
    const currentSession = session;
    try {
      const job = await api("/api/ai-batches", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_type: "triage", scope: "selected", issue_numbers: numbers, skip_existing: true }),
      });
      renderBatchStatus(job);
      if (currentSession !== session || !dialog.open) return;
      jobId = job.id;
      startButton.hidden = true;
      applyButton.hidden = false;
      document.querySelector("#triageReviewScope").hidden = true;
      if (form.querySelector('input[value="selected"]').checked) {
        state.selectedIssues.clear();
        document.querySelectorAll(".issue-select").forEach((checkbox) => { checkbox.checked = false; });
        updateSelectionControls();
      }
      loadReview();
    } catch (error) {
      if (currentSession === session) message.textContent = error.message;
    } finally {
      creating = false;
      if (!jobId) {
        form.querySelector('input[value="selected"]').disabled = !state.selectedIssues.size;
        form.querySelector('input[value="filtered"]').disabled = false;
      }
      updateControls();
    }
  });

  form.querySelectorAll('input[name="scope"]').forEach((input) => input.addEventListener("change", () => loadDraft(true)));
  preserve.addEventListener("change", () => renderItems(pageItems));
  ["Previous", "Next"].forEach((direction) => document.querySelector(`#triageReview${direction}`).addEventListener("click", () => {
    page += direction === "Next" ? 1 : -1;
    jobId ? loadReview() : loadDraft();
  }));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const items = plannedItems();
    if (saving || !terminal || !items.length) return;
    saving = true;
    window.clearTimeout(timer);
    preserve.disabled = true;
    renderItems(pageItems);
    message.textContent = "正在填写识别结果…";
    try {
      const result = await api("/api/issues/identification", {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
      });
      basePlan = null;
      planSignature = null;
      edits.clear();
      preserve.checked = true;
      await loadReview();
      await loadIssues();
      message.textContent = `已填写 ${result.updated} 条。${result.conflicts ? ` ${result.conflicts} 条数据已变化，已跳过。` : ""}`;
      showToast(`已填写 ${result.updated} 条识别结果`);
    } catch (error) {
      message.textContent = error.message;
    } finally {
      saving = false;
      preserve.disabled = false;
      renderItems(pageItems);
    }
  });
  document.querySelector("#viewTriageReview").addEventListener("click", () => {
    if (state.activeBatchId) window.triageReview.openBatch(state.activeBatchId);
  });
  document.querySelector("#closeTriageReview").addEventListener("click", () => { if (!saving && !creating) dialog.close(); });
  dialog.addEventListener("cancel", (event) => { if (saving || creating) event.preventDefault(); });
  dialog.addEventListener("close", () => { session += 1; window.clearTimeout(timer); });
})();
