const CHAT_SETTINGS_KEY = "llm_gateway_chat";
const ADMIN_SETTINGS_KEY = "llm_gateway_admin";

const chatElements = {
  envPill: document.getElementById("env-pill"),
  baseUrl: document.getElementById("base-url"),
  apiKey: document.getElementById("api-key"),
  tenantSelect: document.getElementById("tenant-select"),
  keySelect: document.getElementById("key-select"),
  saveSettings: document.getElementById("save-settings"),
  clearSettings: document.getElementById("clear-settings"),
  reloadKeys: document.getElementById("reload-keys"),
  fetchTenants: document.getElementById("fetch-tenants"),
  model: document.getElementById("model"),
  maxTokens: document.getElementById("max-tokens"),
  temperature: document.getElementById("temperature"),
  prompt: document.getElementById("prompt"),
  sendChat: document.getElementById("send-chat"),
  clearChat: document.getElementById("clear-chat"),
  sessionStatus: document.getElementById("session-status"),
  chatStatus: document.getElementById("chat-status"),
  responseBox: document.getElementById("response-box"),
  responseMeta: document.getElementById("response-meta"),
  ragMeta: document.getElementById("rag-meta"),
  ragLog: document.getElementById("rag-log"),
};

const ALL_TENANTS_VALUE = "__all__";

const getChatSettings = () => {
  return JSON.parse(localStorage.getItem(CHAT_SETTINGS_KEY) || "{}");
};

const getAdminSettings = () => JSON.parse(localStorage.getItem(ADMIN_SETTINGS_KEY) || "{}");

const saveChatSettings = () => {
  const payload = {
    baseUrl: chatElements.baseUrl.value.trim(),
    apiKey: chatElements.apiKey.value.trim(),
    model: chatElements.model.value.trim(),
    maxTokens: chatElements.maxTokens.value.trim(),
    temperature: chatElements.temperature.value.trim(),
  };
  localStorage.setItem(CHAT_SETTINGS_KEY, JSON.stringify(payload));
  setStatus(chatElements.sessionStatus, "Session saved.", "ok");
  updateChatEnvPill();
};

const clearChatSettings = () => {
  localStorage.removeItem(CHAT_SETTINGS_KEY);
  chatElements.baseUrl.value = defaultBaseUrl();
  chatElements.apiKey.value = "";
  chatElements.model.value = "";
  chatElements.maxTokens.value = "";
  chatElements.temperature.value = "";
  setStatus(chatElements.sessionStatus, "Session cleared.", "warn");
  updateChatEnvPill();
};

const updateChatEnvPill = () => {
  if (!chatElements.envPill) {
    return;
  }
  const baseUrl = chatElements.baseUrl.value.trim();
  const apiKey = chatElements.apiKey.value.trim();
  if (baseUrl && apiKey) {
    chatElements.envPill.textContent = baseUrl;
    chatElements.envPill.style.color = "var(--accent)";
  } else {
    chatElements.envPill.textContent = "Disconnected";
    chatElements.envPill.style.color = "var(--warn)";
  }
};

const loadChatSettings = () => {
  const saved = getChatSettings();
  chatElements.baseUrl.value = saved.baseUrl || defaultBaseUrl();
  chatElements.apiKey.value = saved.apiKey || "";
  chatElements.model.value = saved.model || "tinyllama:latest";
  chatElements.maxTokens.value = saved.maxTokens || "";
  chatElements.temperature.value = saved.temperature || "";
  updateChatEnvPill();
};

const loadTenantsFromAdmin = async () => {
  const adminSettings = getAdminSettings();
  const tenantSelect = chatElements.tenantSelect;
  tenantSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = adminSettings.adminKey ? "Loading tenants..." : "Admin session required";
  tenantSelect.appendChild(placeholder);

  if (!adminSettings.adminKey) {
    setStatus(chatElements.sessionStatus, "Admin session required to load tenants.", "warn");
    return;
  }

  try {
    const result = await apiFetch("/v1/admin/tenants", { method: "GET" });
    const tenants = (result.tenants || []).map((t) => t.tenant).sort();
    tenantSelect.innerHTML = "";
    const selectPrompt = document.createElement("option");
    selectPrompt.value = "";
    selectPrompt.textContent = tenants.length ? "Select tenant" : "No tenants found";
    tenantSelect.appendChild(selectPrompt);
    if (tenants.length) {
      const allOption = document.createElement("option");
      allOption.value = ALL_TENANTS_VALUE;
      allOption.textContent = "All tenants (show all keys)";
      tenantSelect.appendChild(allOption);
    }
    tenants.forEach((tenant) => {
      const option = document.createElement("option");
      option.value = tenant;
      option.textContent = tenant;
      tenantSelect.appendChild(option);
    });
    setStatus(chatElements.sessionStatus, "Tenants loaded.", "ok");
  } catch (err) {
    tenantSelect.innerHTML = "";
    const errorOption = document.createElement("option");
    errorOption.value = "";
    errorOption.textContent = "Failed to load tenants";
    tenantSelect.appendChild(errorOption);
    setStatus(chatElements.sessionStatus, err.message, "error");
  }
};

const normalizeTenant = (value) => (value || "").trim().toLowerCase();

const renderKeyOptions = (tenant, keys) => {
  const keySelect = chatElements.keySelect;
  keySelect.innerHTML = "";
  const keyPlaceholder = document.createElement("option");
  keyPlaceholder.value = "";
  if (!tenant) {
    keyPlaceholder.textContent = "Select a tenant to see keys";
  } else if (tenant === ALL_TENANTS_VALUE) {
    keyPlaceholder.textContent = keys.length ? "Select a stored key" : "No active keys found";
  } else {
    keyPlaceholder.textContent = keys.length ? "Select a stored key" : "No stored keys for tenant";
  }
  keySelect.appendChild(keyPlaceholder);

  keys.forEach((item, idx) => {
    const option = document.createElement("option");
    option.value = String(idx);
    const label = item.name ? `${item.tenant} - ${item.name}` : item.tenant;
    option.textContent = label;
    option.dataset.apiKey = item.apiKey;
    option.dataset.tenant = item.tenant;
    keySelect.appendChild(option);
  });
};

const getStoredKeys = () => JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");

const filterStoredKeys = (keys, tenant, activeNamesByTenant) => {
  const normalizedTenant = normalizeTenant(tenant);
  return keys.filter((item) => {
    if (item.active === false) {
      return false;
    }
    if (!tenant) {
      return false;
    }
    const normalizedItemTenant = normalizeTenant(item.tenant);
    if (tenant !== ALL_TENANTS_VALUE && normalizedItemTenant !== normalizedTenant) {
      return false;
    }
    if (!activeNamesByTenant) {
      return true;
    }
    const nameSet = activeNamesByTenant.get(normalizedItemTenant) || new Set();
    if (!item.name) {
      return false;
    }
    return nameSet.has(item.name);
  });
};

const fetchActiveKeyNames = async (tenant) => {
  const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
    method: "GET",
  });
  return (result.keys || []).filter((k) => k.active).map((k) => k.name);
};

const loadTenantKeysFromAdmin = async (tenant = "") => {
  const keys = getStoredKeys();
  const adminSettings = getAdminSettings();
  if (!tenant) {
    renderKeyOptions("", []);
    return;
  }

  if (!adminSettings.adminKey) {
    const filtered = filterStoredKeys(keys, tenant, null);
    renderKeyOptions(tenant, filtered);
    setStatus(chatElements.sessionStatus, "Admin session required to verify active keys.", "warn");
    return;
  }

  try {
    if (tenant === ALL_TENANTS_VALUE) {
      const tenantResult = await apiFetch("/v1/admin/tenants", { method: "GET" });
      const tenants = (tenantResult.tenants || []).map((t) => t.tenant);
      const activeNamesByTenant = new Map();
      const results = await Promise.all(
        tenants.map(async (t) => {
          const names = await fetchActiveKeyNames(t);
          activeNamesByTenant.set(normalizeTenant(t), new Set(names));
          return names.length;
        })
      );
      const filtered = filterStoredKeys(keys, tenant, activeNamesByTenant);
      renderKeyOptions(tenant, filtered);
      if (!results.some((count) => count > 0)) {
        setStatus(chatElements.sessionStatus, "No active keys found.", "warn");
      }
      return;
    }

    const activeNames = await fetchActiveKeyNames(tenant);
    const activeNamesByTenant = new Map([[normalizeTenant(tenant), new Set(activeNames)]]);
    const filtered = filterStoredKeys(keys, tenant, activeNamesByTenant);
    renderKeyOptions(tenant, filtered);
  } catch (err) {
    const filtered = filterStoredKeys(keys, tenant, null);
    renderKeyOptions(tenant, filtered);
    setStatus(chatElements.sessionStatus, err.message, "error");
  }
};

const syncKeyFromTenant = () => {
  const tenant = chatElements.tenantSelect.value;
  loadTenantKeysFromAdmin(tenant);
  if (!tenant || tenant === ALL_TENANTS_VALUE) {
    return;
  }
  const options = Array.from(chatElements.keySelect.options);
  const match = options.find((opt) => opt.dataset.tenant === tenant);
  if (match) {
    chatElements.keySelect.value = match.value;
    chatElements.apiKey.value = match.dataset.apiKey || "";
    updateChatEnvPill();
  }
};

chatElements.keySelect?.addEventListener("change", (event) => {
  const selected = event.target.selectedOptions[0];
  if (!selected || !selected.dataset.apiKey) {
    return;
  }
  chatElements.apiKey.value = selected.dataset.apiKey;
  if (selected.dataset.tenant) {
    chatElements.tenantSelect.value = selected.dataset.tenant;
  }
  updateChatEnvPill();
});

chatElements.tenantSelect?.addEventListener("change", () => {
  syncKeyFromTenant();
});

chatElements.keySelect?.addEventListener("focus", () => {
  loadTenantKeysFromAdmin(chatElements.tenantSelect.value);
});

chatElements.saveSettings?.addEventListener("click", saveChatSettings);
chatElements.clearSettings?.addEventListener("click", clearChatSettings);
chatElements.reloadKeys?.addEventListener("click", () => {
  loadTenantKeysFromAdmin(chatElements.tenantSelect.value);
  loadTenantsFromAdmin();
  setStatus(chatElements.sessionStatus, "Keys reloaded and tenants refreshed.", "ok");
});

chatElements.fetchTenants?.addEventListener("click", () => {
  loadTenantsFromAdmin();
});

chatElements.clearChat?.addEventListener("click", () => {
  chatElements.prompt.value = "";
  chatElements.responseBox.textContent = "";
  chatElements.responseMeta.textContent = "No response yet.";
  if (chatElements.ragMeta) {
    chatElements.ragMeta.textContent = "RAG: --";
  }
  if (chatElements.ragLog) {
    chatElements.ragLog.textContent = "";
  }
  setStatus(chatElements.chatStatus, "", "info");
});

chatElements.sendChat?.addEventListener("click", async () => {
  const baseUrl = chatElements.baseUrl.value.trim();
  const apiKey = chatElements.apiKey.value.trim();
  const model = chatElements.model.value.trim();
  const prompt = chatElements.prompt.value.trim();
  const maxTokens = chatElements.maxTokens.value.trim();
  const temperature = chatElements.temperature.value.trim();

  if (!baseUrl) {
    setStatus(chatElements.chatStatus, "Base URL is required.", "warn");
    return;
  }
  if (!apiKey) {
    setStatus(chatElements.chatStatus, "Tenant API key is required.", "warn");
    return;
  }
  if (!model) {
    setStatus(chatElements.chatStatus, "Model is required.", "warn");
    return;
  }
  if (!prompt) {
    setStatus(chatElements.chatStatus, "Prompt is required.", "warn");
    return;
  }

  const payload = {
    model,
    messages: [{ role: "user", content: prompt }],
  };
  if (maxTokens) {
    payload.max_tokens = Number(maxTokens);
  }
  if (temperature) {
    payload.temperature = Number(temperature);
  }

  setStatus(chatElements.chatStatus, "Sending prompt...", "info");
  chatElements.responseBox.textContent = "";
  chatElements.responseMeta.textContent = "Awaiting response...";
  if (chatElements.ragMeta) {
    chatElements.ragMeta.textContent = "RAG: pending...";
  }
  if (chatElements.ragLog) {
    chatElements.ragLog.textContent = "";
  }

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let message = response.statusText || "Request failed";
      try {
        const error = await response.json();
        message = error?.error?.message || message;
      } catch (err) {
        // ignore
      }
      throw new Error(message);
    }
    const data = await response.json();
    chatElements.responseMeta.textContent = `id: ${data.id} | model: ${data.model} | created: ${new Date(
      data.created * 1000
    ).toLocaleString()}`;
    chatElements.responseBox.textContent = data.content || "(empty response)";
    const ragStatus = response.headers.get("x-rag") || "bypass";
    const ragChunks = response.headers.get("x-rag-chunks") || "0";
    if (chatElements.ragMeta) {
      chatElements.ragMeta.textContent = `RAG: ${ragStatus} | chunks: ${ragChunks}`;
    }
    if (chatElements.ragLog) {
      const headerLines = [
        `x-rag: ${ragStatus}`,
        `x-rag-chunks: ${ragChunks}`,
        `x-provider: ${response.headers.get("x-provider") || "--"}`,
        `x-route-reason: ${response.headers.get("x-route-reason") || "--"}`,
        `x-cache: ${response.headers.get("x-cache") || "--"}`,
      ];
      chatElements.ragLog.textContent = headerLines.join("\n");
    }
    setStatus(chatElements.chatStatus, "Response received.", "ok");
    saveChatSettings();
  } catch (err) {
    setStatus(chatElements.chatStatus, err.message, "error");
    chatElements.responseMeta.textContent = "Request failed.";
  }
});

loadChatSettings();
renderKeyOptions("", []);
loadTenantsFromAdmin();
