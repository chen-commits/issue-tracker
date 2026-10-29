/* Model credentials are never cached in browser storage. */
(() => {
  const form = document.querySelector("#modelSettingsForm");
  const selector = document.querySelector("#modelProfileSelect");
  const message = document.querySelector("#modelSettingsMessage");
  const activate = document.querySelector("#activateModelProfile");
  const testButton = document.querySelector("#testModelConnection");
  let settings = null;
  let selectedId = "env";
  let pollTimer = null;
  let testing = false;
  let busy = false;
  let dirty = false;
  let testStartedAt = 0;
  const fields = ["name", "model", "base_url", "api_key", "timeout", "max_output_tokens", "reasoning_effort", "token_parameter"];

  function notify(text, error = false) {
    message.textContent = text;
    message.classList.toggle("model-error", error);
  }

  function setBusy(value) {
    busy = value;
    form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = value; });
    selector.disabled = value;
    document.querySelector("#newModelProfile").disabled = value;
    activate.disabled = value || !selectedId || dirty;
    testButton.disabled = value || testing;
  }

  function fill(profile) {
    dirty = false;
    selectedId = profile?.id || null;
    form.reset();
    fields.forEach((field) => {
      if (field !== "api_key") form.elements.namedItem(field).value = profile?.[field] ?? ({ timeout: 120, max_output_tokens: 16384, token_parameter: "max_completion_tokens" }[field] ?? "");
    });
    form.elements.api_key.value = "";
    form.elements.api_key.placeholder = profile?.has_api_key ? "密钥已保存，留空保留" : "填写 API Key";
    ["json_mode", "send_temperature"].forEach((field) => { form.elements.namedItem(field).checked = profile?.[field] ?? true; });
    selector.value = selectedId || "";
    activate.disabled = !selectedId;
    notify(selectedId === "env" ? "当前为环境变量配置；编辑后保存将创建独立配置。" : "");
  }

  async function load(preferredId) {
    const result = await api("/api/model-settings");
    settings = result;
    selector.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "新增模型配置";
    selector.append(placeholder);
    result.profiles.forEach((profile) => {
      const option = document.createElement("option");
      option.value = profile.id;
      option.textContent = `${profile.name} · ${profile.model}${profile.id === result.active_id ? "（当前启用）" : ""}`;
      selector.append(option);
    });
    const activeProfile = result.profiles.find((profile) => profile.id === result.active_id);
    document.querySelector("#activeModelSummary").textContent = activeProfile
      ? `当前启用：${activeProfile.name} / ${activeProfile.model}${activeProfile.has_api_key ? "" : "（未配置密钥）"}` : "尚未启用模型";
    fill(result.profiles.find((profile) => profile.id === (preferredId || result.active_id)));
  }

  function payload() {
    const value = Object.fromEntries(new FormData(form).entries());
    value.profile_id = selectedId;
    value.timeout = Number(value.timeout);
    value.max_output_tokens = Number(value.max_output_tokens);
    value.json_mode = form.elements.json_mode.checked;
    value.send_temperature = form.elements.send_temperature.checked;
    return value;
  }

  async function save(event) {
    event.preventDefault();
    if (busy) return;
    const shouldActivate = event.submitter?.value === "activate";
    const wasActive = selectedId && selectedId !== "env" && selectedId === settings?.active_id;
    setBusy(true);
    notify("正在保存配置…");
    try {
      const result = await api("/api/model-settings/profiles", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()),
      });
      form.elements.api_key.value = "";
      selectedId = result.profile.id;
      if (shouldActivate) await enable(selectedId);
      await load(selectedId);
      notify(shouldActivate ? "配置已保存并启用，新请求立即生效。"
        : wasActive ? "当前启用配置已更新，新请求立即生效。" : "配置已保存，尚未切换当前启用模型。");
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function enable(id) {
    return api("/api/model-settings/activate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile_id: id }),
    });
  }

  async function poll(id) {
    try {
      const result = await api(`/api/model-settings/tests/${encodeURIComponent(id)}`);
      const running = result.status === "running";
      const elapsed = running ? (Date.now() - testStartedAt) / 1000 : result.elapsed_ms / 1000;
      document.querySelector("#modelTestTitle").textContent = running ? "正在验证模型…" : result.status === "succeeded" ? "模型验证通过" : "模型验证失败";
      document.querySelector("#modelTestResult").classList.toggle("model-error", result.status === "failed");
      document.querySelector("#modelTestMeta").textContent = `测试编号：${id} · ${running ? "已等待" : "耗时"} ${elapsed.toFixed(1)} 秒`;
      document.querySelector("#modelTestDetails").textContent = running
        ? "后台正在请求模型，当前测试使用点击时的表单参数。"
        : [result.message, result.result?.response || "", result.result?.usage ? JSON.stringify(result.result.usage, null, 2) : ""].filter(Boolean).join("\n\n");
      if (running) {
        pollTimer = window.setTimeout(() => poll(id), 1000);
      } else {
        testing = false;
        setBusy(busy);
      }
    } catch (error) {
      testing = false;
      setBusy(busy);
      document.querySelector("#modelTestTitle").textContent = "测试状态读取失败";
      document.querySelector("#modelTestDetails").textContent = error.message;
    }
  }

  testButton.addEventListener("click", async () => {
    if (!form.reportValidity() || testing) return;
    testing = true;
    testButton.disabled = true;
    window.clearTimeout(pollTimer);
    notify("正在发起连接测试…");
    try {
      testStartedAt = Date.now();
      const result = await api("/api/model-settings/tests", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()),
      });
      document.querySelector("#modelTestResult").hidden = false;
      notify("测试已提交，无需保存或启用配置。测试结果见下方。");
      await poll(result.id);
    } catch (error) {
      testing = false;
      setBusy(busy);
      notify(error.message, true);
    }
  });

  form.addEventListener("submit", save);
  form.addEventListener("input", () => { dirty = true; activate.disabled = true; });
  selector.addEventListener("change", () => fill(settings.profiles.find((profile) => profile.id === selector.value)));
  document.querySelector("#newModelProfile").addEventListener("click", () => { fill(null); form.elements.name.focus(); });
  activate.addEventListener("click", async () => {
    if (!selectedId || busy) return;
    setBusy(true);
    try {
      await enable(selectedId);
      await load(selectedId);
      notify("所选配置已启用，新请求立即生效。");
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  });

  const tabs = [...document.querySelectorAll('.page-tabs [role="tab"]')];
  function selectTab(tab) {
    tabs.forEach((item) => {
      const selected = item === tab;
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute("aria-controls")).hidden = !selected;
    });
    if (tab.id === "modelsTab" && !settings) {
      setBusy(true);
      load().catch((error) => notify(error.message, true)).finally(() => setBusy(false));
    }
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1]
        : tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      selectTab(next);
      next.focus();
    });
  });
})();
