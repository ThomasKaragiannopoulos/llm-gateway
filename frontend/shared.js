const STORAGE_KEY = "llm_gateway_admin";
const KEYS_KEY = "llm_gateway_keys";

const getSettings = () => {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  const baseUrlInput = document.getElementById("base-url");
  const adminKeyInput = document.getElementById("admin-key");
  return {
    baseUrl: saved.baseUrl || (baseUrlInput ? baseUrlInput.value.trim() : ""),
    adminKey: saved.adminKey || (adminKeyInput ? adminKeyInput.value.trim() : ""),
  };
};

const defaultBaseUrl = () => {
  if (window.location.protocol.startsWith("http")) {
    return window.location.origin;
  }
  return "http://localhost:8000";
};

const loadSettings = () => {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  const baseUrlInput = document.getElementById("base-url");
  const adminKeyInput = document.getElementById("admin-key");
  if (baseUrlInput) {
    baseUrlInput.value = saved.baseUrl || defaultBaseUrl();
  }
  if (adminKeyInput) {
    adminKeyInput.value = saved.adminKey || "";
  }
};

const saveSettings = (statusEl, envPill) => {
  const baseUrlInput = document.getElementById("base-url");
  const adminKeyInput = document.getElementById("admin-key");
  const payload = {
    baseUrl: baseUrlInput ? baseUrlInput.value.trim() : "",
    adminKey: adminKeyInput ? adminKeyInput.value.trim() : "",
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  if (statusEl) {
    setStatus(statusEl, "Session saved.", "ok");
  }
  updateEnvPill(envPill);
};

const clearSettings = (statusEl, envPill) => {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(KEYS_KEY);
  loadSettings();
  if (statusEl) {
    setStatus(statusEl, "Session cleared.", "warn");
  }
  updateEnvPill(envPill);
};

const updateEnvPill = (envPill) => {
  if (!envPill) {
    return;
  }
  const { baseUrl, adminKey } = getSettings();
  if (baseUrl && adminKey) {
    envPill.textContent = baseUrl;
    envPill.style.color = "var(--accent)";
  } else {
    envPill.textContent = "Disconnected";
    envPill.style.color = "var(--warn)";
  }
};

const setStatus = (el, message, tone = "info") => {
  if (!el) {
    return;
  }
  el.textContent = message;
  const color = {
    ok: "var(--accent)",
    warn: "var(--warn)",
    error: "var(--danger)",
    info: "var(--muted)",
  }[tone];
  el.style.color = color || "var(--muted)";
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
    let errorBody = null;
    try {
      errorBody = await response.json();
      message = errorBody?.error?.message || message;
    } catch (err) {
      message = response.statusText || message;
    }
    const reqError = new Error(message);
    reqError.status = response.status;
    reqError.body = errorBody;
    throw reqError;
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

const renderKeyList = (keyListEl) => {
  if (!keyListEl) {
    return;
  }
  const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
  keyListEl.innerHTML = "";
  if (!keys.length) {
    keyListEl.innerHTML = "<div class=\"muted\">No stored keys yet.</div>";
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
    keyListEl.appendChild(div);
  });
};
