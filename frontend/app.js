const STORAGE_KEY = "llm_gateway_admin";
const KEYS_KEY = "llm_gateway_keys";

const elements = {
  baseUrl: document.getElementById("base-url"),
  adminKey: document.getElementById("admin-key"),
  saveSettings: document.getElementById("save-settings"),
  clearSettings: document.getElementById("clear-settings"),
  sessionStatus: document.getElementById("session-status"),
  envPill: document.getElementById("env-pill"),
  tenantName: document.getElementById("tenant-name"),
  tenantTier: document.getElementById("tenant-tier"),
  createTenant: document.getElementById("create-tenant"),
  tenantStatus: document.getElementById("tenant-status"),
  keyTenant: document.getElementById("key-tenant"),
  keyName: document.getElementById("key-name"),
  createKey: document.getElementById("create-key"),
  keyResult: document.getElementById("key-result"),
  keyValue: document.getElementById("key-value"),
  copyLatest: document.getElementById("copy-latest"),
  keyList: document.getElementById("key-list"),
  listTenant: document.getElementById("list-tenant"),
  listKeys: document.getElementById("list-keys"),
  tenantKeys: document.getElementById("tenant-keys"),
  keysStatus: document.getElementById("keys-status"),
  limitsTenant: document.getElementById("limits-tenant"),
  tokenLimit: document.getElementById("token-limit"),
  spendLimit: document.getElementById("spend-limit"),
  setLimits: document.getElementById("set-limits"),
  limitsStatus: document.getElementById("limits-status"),
  usageTenant: document.getElementById("usage-tenant"),
  fetchUsage: document.getElementById("fetch-usage"),
  usageRequests: document.getElementById("usage-requests"),
  usageTokens: document.getElementById("usage-tokens"),
  usageCost: document.getElementById("usage-cost"),
  usageStatus: document.getElementById("usage-status"),
  healthChip: document.getElementById("health-chip"),
  rotateAdmin: document.getElementById("rotate-admin"),
  copyAdmin: document.getElementById("copy-admin"),
  adminKeyValue: document.getElementById("admin-key-value"),
  revokeKeyInput: document.getElementById("revoke-key"),
  revokeKeyBtn: document.getElementById("revoke-key-btn"),
  revokeStatus: document.getElementById("revoke-status"),
  loadTenants: document.getElementById("load-tenants"),
  tenantsBody: document.getElementById("tenants-body"),
  tenantsStatus: document.getElementById("tenants-status"),
  detailName: document.getElementById("detail-name"),
  detailTier: document.getElementById("detail-tier"),
  detailCreated: document.getElementById("detail-created"),
  detailUsage: document.getElementById("detail-usage"),
  detailKeys: document.getElementById("detail-keys"),
  detailRequests: document.getElementById("detail-requests"),
  detailTokens: document.getElementById("detail-tokens"),
  detailCost: document.getElementById("detail-cost"),
  detailKeysList: document.getElementById("detail-keys-list"),
  detailStatus: document.getElementById("detail-status"),
  detailRevokeInput: document.getElementById("detail-revoke-input"),
  detailRevoke: document.getElementById("detail-revoke"),
};

const defaultBaseUrl = () => {
  if (window.location.protocol.startsWith("http")) {
    return window.location.origin;
  }
  return "http://localhost:8000";
};

const loadSettings = () => {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  elements.baseUrl.value = saved.baseUrl || defaultBaseUrl();
  elements.adminKey.value = saved.adminKey || "";
};

const saveSettings = () => {
  const payload = {
    baseUrl: elements.baseUrl.value.trim(),
    adminKey: elements.adminKey.value.trim(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  setStatus(elements.sessionStatus, "Session saved.", "ok");
  updateEnvPill();
};

const clearSettings = () => {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(KEYS_KEY);
  loadSettings();
  renderKeyList();
  elements.keyValue.textContent = "No key generated yet.";
  elements.copyLatest.disabled = true;
  setStatus(elements.sessionStatus, "Session cleared.", "warn");
  updateEnvPill();
};

const getSettings = () => {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  return {
    baseUrl: saved.baseUrl || elements.baseUrl.value.trim(),
    adminKey: saved.adminKey || elements.adminKey.value.trim(),
  };
};

const apiFetch = async (path, options = {}) => {
  const { baseUrl, adminKey } = getSettings();
  if (!baseUrl || !adminKey) {
    throw new Error("Missing base URL or admin key.");
  }
  const url = `${baseUrl.replace(/\/$/, "")}${path}`;
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${adminKey}`,
    ...(options.headers || {}),
  };
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let message = "Request failed";
    try {
      const error = await response.json();
      message = error?.error?.message || message;
    } catch (err) {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  return response.json();
};

const healthFetch = async (path) => {
  const { baseUrl } = getSettings();
  if (!baseUrl) {
    throw new Error("Missing base URL.");
  }
  const url = `${baseUrl.replace(/\/$/, "")}${path}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(response.statusText || "Health check failed");
  }
  return response.json();
};

const setStatus = (el, message, tone = "info") => {
  el.textContent = message;
  const color = {
    ok: "var(--accent)",
    warn: "var(--warn)",
    error: "var(--danger)",
    info: "var(--muted)",
  }[tone];
  el.style.color = color || "var(--muted)";
};

const renderKeyList = () => {
  const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
  elements.keyList.innerHTML = "";
  if (!keys.length) {
    elements.keyList.innerHTML = "<div class=\"muted\">No stored keys yet.</div>";
    return;
  }
  keys.slice(0, 6).forEach((item) => {
    const div = document.createElement("div");
    div.className = "key-item";
    const displayName = item.name ? ` • ${item.name}` : "";
    div.innerHTML = `
      <strong>${item.tenant}${displayName}</strong>
      <span>${new Date(item.createdAt).toLocaleString()}</span>
      <span class="pill">**** ${item.apiKey.slice(-6)}</span>
    `;
    elements.keyList.appendChild(div);
  });
};

const updateEnvPill = () => {
  const { baseUrl, adminKey } = getSettings();
  if (baseUrl && adminKey) {
    elements.envPill.textContent = baseUrl;
    elements.envPill.style.color = "var(--accent)";
  } else {
    elements.envPill.textContent = "Disconnected";
    elements.envPill.style.color = "var(--warn)";
  }
};

let selectedTenant = null;

const setSelectedTenant = (tenant) => {
  selectedTenant = tenant;
  elements.detailName.textContent = tenant ? tenant.tenant : "No tenant selected";
  elements.detailTier.textContent = `Tier: ${tenant ? tenant.tier : "--"}`;
  elements.detailCreated.textContent = `Created: ${tenant?.created_at ? new Date(tenant.created_at).toLocaleString() : "--"}`;
  elements.detailRequests.textContent = "--";
  elements.detailTokens.textContent = "--";
  elements.detailCost.textContent = "--";
  elements.detailKeysList.innerHTML = "";
};

const renderTenants = (tenants) => {
  elements.tenantsBody.innerHTML = "";
  if (!tenants.length) {
    elements.tenantsBody.innerHTML = "<tr><td colspan=\"5\">No tenants found.</td></tr>";
    return;
  }
  tenants.forEach((t) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${t.tenant}</td>
      <td>${t.tier}</td>
      <td>${t.token_limit_per_day ?? "--"}</td>
      <td>${t.spend_limit_per_day_usd ?? "--"}</td>
      <td>${t.created_at ? new Date(t.created_at).toLocaleDateString() : "--"}</td>
    `;
    row.addEventListener("click", () => setSelectedTenant(t));
    elements.tenantsBody.appendChild(row);
  });
};

elements.saveSettings.addEventListener("click", async () => {
  saveSettings();
  await runHealthCheck();
});
elements.clearSettings.addEventListener("click", () => clearSettings());

elements.createTenant.addEventListener("click", async () => {
  const tenant = elements.tenantName.value.trim();
  if (!tenant) {
    setStatus(elements.tenantStatus, "Tenant name is required.", "warn");
    return;
  }
  const tier = elements.tenantTier.value.trim();
  try {
    const result = await apiFetch("/v1/admin/tenants", {
      method: "POST",
      body: JSON.stringify({ tenant, tier: tier || null }),
    });
    setStatus(elements.tenantStatus, `Tenant ${result.tenant} created (${result.tier}).`, "ok");
  } catch (err) {
    setStatus(elements.tenantStatus, err.message, "error");
  }
});

elements.createKey.addEventListener("click", async () => {
  const tenant = elements.keyTenant.value.trim();
  const name = elements.keyName.value.trim();
  if (!tenant) {
    setStatus(elements.sessionStatus, "Tenant name is required.", "warn");
    return;
  }
  if (!name) {
    setStatus(elements.sessionStatus, "Key name is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    elements.keyValue.textContent = result.api_key;
    elements.copyLatest.disabled = false;
    const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
    keys.unshift({ tenant: result.tenant, name: result.name, apiKey: result.api_key, createdAt: Date.now() });
    localStorage.setItem(KEYS_KEY, JSON.stringify(keys.slice(0, 12)));
    renderKeyList();
    setStatus(elements.sessionStatus, `Key created for ${result.tenant}.`, "ok");
  } catch (err) {
    setStatus(elements.sessionStatus, err.message, "error");
  }
});

elements.copyLatest.addEventListener("click", async () => {
  const text = elements.keyValue.textContent;
  if (!text || text.includes("No key")) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus(elements.sessionStatus, "Key copied to clipboard.", "ok");
  } catch (err) {
    setStatus(elements.sessionStatus, "Copy failed. Select the key manually.", "warn");
  }
});

elements.setLimits.addEventListener("click", async () => {
  const tenant = elements.limitsTenant.value.trim();
  if (!tenant) {
    setStatus(elements.limitsStatus, "Tenant name is required.", "warn");
    return;
  }
  const tokenValue = elements.tokenLimit.value.trim();
  const spendValue = elements.spendLimit.value.trim();
  const payload = {
    tenant,
    token_limit_per_day: tokenValue ? Number(tokenValue) : null,
    spend_limit_per_day_usd: spendValue ? Number(spendValue) : null,
  };
  try {
    await apiFetch("/v1/admin/limits", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setStatus(elements.limitsStatus, "Limits updated.", "ok");
  } catch (err) {
    setStatus(elements.limitsStatus, err.message, "error");
  }
});

elements.fetchUsage.addEventListener("click", async () => {
  const tenant = elements.usageTenant.value.trim();
  if (!tenant) {
    setStatus(elements.usageStatus, "Tenant name is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/usage/${encodeURIComponent(tenant)}`, {
      method: "GET",
    });
    elements.usageRequests.textContent = result.requests;
    elements.usageTokens.textContent = result.tokens;
    elements.usageCost.textContent = Number(result.cost_usd || 0).toFixed(4);
    setStatus(elements.usageStatus, "Usage loaded.", "ok");
  } catch (err) {
    setStatus(elements.usageStatus, err.message, "error");
  }
});

elements.rotateAdmin?.addEventListener("click", async () => {
  try {
    const result = await apiFetch("/v1/admin/keys/rotate", { method: "POST" });
    elements.adminKeyValue.textContent = result.admin_api_key;
    elements.copyAdmin.disabled = false;
    elements.adminKey.value = result.admin_api_key;
    const settings = getSettings();
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ baseUrl: settings.baseUrl, adminKey: result.admin_api_key })
    );
    setStatus(
      elements.sessionStatus,
      "Admin key rotated. Update ADMIN_API_KEY and restart to persist.",
      "warn"
    );
  } catch (err) {
    setStatus(elements.sessionStatus, err.message, "error");
  }
});

elements.copyAdmin?.addEventListener("click", async () => {
  const text = elements.adminKeyValue.textContent;
  if (!text || text.includes("No rotation")) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus(elements.sessionStatus, "Admin key copied to clipboard.", "ok");
  } catch (err) {
    setStatus(elements.sessionStatus, "Copy failed. Select the key manually.", "warn");
  }
});

elements.revokeKeyBtn?.addEventListener("click", async () => {
  const apiKey = elements.revokeKeyInput.value.trim();
  if (!apiKey) {
    setStatus(elements.revokeStatus, "API key is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch("/v1/admin/keys/revoke", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    });
    setStatus(
      elements.revokeStatus,
      result.tenant ? `Key revoked for ${result.tenant}.` : "Key revoked.",
      "ok"
    );
  } catch (err) {
    setStatus(elements.revokeStatus, err.message, "error");
  }
});

elements.listKeys.addEventListener("click", async () => {
  const tenant = elements.listTenant.value.trim();
  if (!tenant) {
    setStatus(elements.keysStatus, "Tenant name is required.", "warn");
    return;
  }
  elements.tenantKeys.innerHTML = "";
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "GET",
    });
    if (!result.keys.length) {
      elements.tenantKeys.innerHTML = "<div class=\"muted\">No keys for tenant.</div>";
    } else {
      result.keys.forEach((k) => {
        const div = document.createElement("div");
        div.className = "key-item";
        const created = k.created_at ? new Date(k.created_at).toLocaleString() : "unknown";
        const state = k.active ? "active" : "revoked";
        div.innerHTML = `
          <strong>${state.toUpperCase()} • ${k.name}</strong>
          <span>${created}</span>
          <span class="pill">hash ****${k.key_last6}</span>
        `;
        elements.tenantKeys.appendChild(div);
      });
    }
    setStatus(elements.keysStatus, "Keys loaded.", "ok");
  } catch (err) {
    setStatus(elements.keysStatus, err.message, "error");
  }
});

elements.loadTenants?.addEventListener("click", async () => {
  try {
    const result = await apiFetch("/v1/admin/tenants", { method: "GET" });
    renderTenants(result.tenants || []);
    setSelectedTenant(null);
    setStatus(elements.tenantsStatus, "Tenants loaded.", "ok");
  } catch (err) {
    setStatus(elements.tenantsStatus, err.message, "error");
  }
});

elements.detailUsage?.addEventListener("click", async () => {
  if (!selectedTenant) {
    setStatus(elements.detailStatus, "Select a tenant first.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/usage/${encodeURIComponent(selectedTenant.tenant)}`, {
      method: "GET",
    });
    elements.detailRequests.textContent = result.requests;
    elements.detailTokens.textContent = result.tokens;
    elements.detailCost.textContent = Number(result.cost_usd || 0).toFixed(4);
    setStatus(elements.detailStatus, "Usage loaded.", "ok");
  } catch (err) {
    setStatus(elements.detailStatus, err.message, "error");
  }
});

elements.detailKeys?.addEventListener("click", async () => {
  if (!selectedTenant) {
    setStatus(elements.detailStatus, "Select a tenant first.", "warn");
    return;
  }
  elements.detailKeysList.innerHTML = "";
  try {
    const result = await apiFetch(
      `/v1/admin/tenants/${encodeURIComponent(selectedTenant.tenant)}/keys`,
      { method: "GET" }
    );
    if (!result.keys.length) {
      elements.detailKeysList.innerHTML = "<div class=\"muted\">No keys for tenant.</div>";
    } else {
      result.keys.forEach((k) => {
        const div = document.createElement("div");
        div.className = "key-item";
        const created = k.created_at ? new Date(k.created_at).toLocaleString() : "unknown";
        const state = k.active ? "active" : "revoked";
        div.innerHTML = `
          <strong>${state.toUpperCase()} • ${k.name}</strong>
          <span>${created}</span>
          <span class="pill">hash ****${k.key_last6}</span>
        `;
        elements.detailKeysList.appendChild(div);
      });
    }
    setStatus(elements.detailStatus, "Keys loaded.", "ok");
  } catch (err) {
    setStatus(elements.detailStatus, err.message, "error");
  }
});

elements.detailRevoke?.addEventListener("click", async () => {
  const apiKey = elements.detailRevokeInput.value.trim();
  if (!apiKey) {
    setStatus(elements.detailStatus, "API key is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch("/v1/admin/keys/revoke", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    });
    setStatus(
      elements.detailStatus,
      result.tenant ? `Key revoked for ${result.tenant}.` : "Key revoked.",
      "ok"
    );
  } catch (err) {
    setStatus(elements.detailStatus, err.message, "error");
  }
});

const runHealthCheck = async () => {
  setStatus(elements.sessionStatus, "Checking gateway health...", "info");
  if (elements.healthChip) {
    elements.healthChip.textContent = "Status: checking...";
  }
  try {
    const api = await healthFetch("/health");
    const ollama = await healthFetch("/health/ollama");
    const apiStatus = api.status || "ok";
    const ollamaStatus = ollama.status || "unknown";
    setStatus(elements.sessionStatus, `Health ok (api: ${apiStatus}, ollama: ${ollamaStatus}).`, "ok");
    if (elements.healthChip) {
      elements.healthChip.textContent = `Status: ok (api: ${apiStatus}, ollama: ${ollamaStatus})`;
      elements.healthChip.dataset.state = "ok";
    }
  } catch (err) {
    setStatus(elements.sessionStatus, err.message, "error");
    if (elements.healthChip) {
      elements.healthChip.textContent = `Status: error (${err.message})`;
      elements.healthChip.dataset.state = "error";
    }
  }
};

loadSettings();
renderKeyList();
updateEnvPill();
