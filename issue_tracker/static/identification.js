(() => {
  const dialog = document.querySelector("#identificationDialog");
  const form = document.querySelector("#identificationForm");
  const preview = document.querySelector("#identificationPreview");
  const examples = document.querySelector("#identificationExamples");
  const message = document.querySelector("#identificationMessage");
  const submit = document.querySelector("#applyIdentification");
  let plan = null;
  let previewRequest = 0;
  let saving = false;

  async function refreshPreview() {
    const requestId = ++previewRequest;
    plan = null;
    submit.disabled = true;
    submit.textContent = "确认填写";
    examples.replaceChildren();
    message.textContent = "";
    preview.textContent = "正在预览填写范围…";
    const data = new FormData(form);
    try {
      const result = await api("/api/issues/identification/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: data.get("scope"), result: data.get("result"),
          skip_existing: data.has("skip_existing"),
          issue_numbers: [...state.selectedIssues], filters: currentFilterPayload(),
        }),
      });
      if (requestId !== previewRequest || !dialog.open) return;
      plan = result.items;
      preview.textContent = `范围 ${result.total} 条；将填写 ${plan.length} 条：`
        + Object.entries(result.counts).map(([value, count]) => `${value} ${count} 条`).join("，")
        + `。保留已有 ${result.existing_skipped} 条，未初筛/已过期跳过 ${result.unavailable_skipped} 条，内容相同 ${result.unchanged} 条。`;
      result.examples.forEach((item) => {
        const row = document.createElement("li");
        row.textContent = `#${item.number} ${item.title}：${item.previous || "未填写"} → ${item.result}`;
        examples.append(row);
      });
      submit.textContent = `确认填写 ${plan.length} 条`;
      submit.disabled = !plan.length;
    } catch (error) {
      if (requestId === previewRequest) preview.textContent = error.message;
    }
  }

  document.querySelector("#bulkIdentificationButton").addEventListener("click", () => {
    form.reset();
    const selected = form.querySelector('input[value="selected"]');
    const filtered = form.querySelector('input[value="filtered"]');
    selected.disabled = state.selectedIssues.size === 0;
    filtered.disabled = state.filteredTotal === 0;
    selected.checked = state.selectedIssues.size > 0;
    filtered.checked = state.selectedIssues.size === 0 && state.filteredTotal > 0;
    document.querySelector("#identificationSelectedCount").textContent = `已选 ${state.selectedIssues.size} 条（支持跨页选择）`;
    document.querySelector("#identificationFilteredCount").textContent = `当前筛选全部 ${state.filteredTotal} 条（含其他页）`;
    dialog.showModal();
    refreshPreview();
  });
  form.addEventListener("change", refreshPreview);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || !plan?.length) return;
    saving = true;
    const items = plan;
    form.querySelectorAll("button,input,select").forEach((control) => { control.disabled = true; });
    message.textContent = "正在填写…";
    try {
      const result = await api("/api/issues/identification", {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
      });
      dialog.close();
      state.selectedIssues.clear();
      state.page = 1;
      showToast(`已填写 ${result.updated} 条${result.conflicts ? `；${result.conflicts} 条期间有变化，已跳过，请重新预览` : ""}`);
      await loadIssues();
    } catch (error) {
      message.textContent = error.message;
    } finally {
      saving = false;
      form.querySelectorAll("button,input,select").forEach((control) => { control.disabled = false; });
    }
  });
  ["#closeIdentification", "#cancelIdentification"].forEach((id) => {
    document.querySelector(id).addEventListener("click", () => { if (!saving) dialog.close(); });
  });
  dialog.addEventListener("cancel", (event) => { if (saving) event.preventDefault(); });
  dialog.addEventListener("close", () => { plan = null; previewRequest += 1; });
})();
