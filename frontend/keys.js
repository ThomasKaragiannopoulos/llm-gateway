const keyElements = {
  envPill: document.getElementById("env-pill"),
  sessionStatus: document.getElementById("session-status"),
  saveSettings: document.getElementById("save-settings"),
  clearSettings: document.getElementById("clear-settings"),
  healthChip: document.getElementById("health-chip"),
  keyTenant: document.getElementById("key-tenant"),
  keyName: document.getElementById("key-name"),
  createKey: document.getElementById("create-key"),
  keyValue: document.getElementById("key-value"),
  copyLatest: document.getElementById("copy-latest"),
  listTenant: document.getElementById("list-tenant"),
  listKeys: document.getElementById("list-keys"),
  tenantKeys: document.getElementById("tenant-keys"),
  keysStatus: document.getElementById("keys-status"),
  importTenant: document.getElementById("import-tenant"),
  importKeyName: document.getElementById("import-key-name"),
  importKeyValue: document.getElementById("import-key-value"),
  importKeyBtn: document.getElementById("import-key-btn"),
  importStatus: document.getElementById("import-status"),
  revokeTenant: document.getElementById("revoke-tenant"),
  revokeKeyName: document.getElementById("revoke-key-name"),
  revokeReason: document.getElementById("revoke-reason"),
  revokeKeyBtn: document.getElementById("revoke-key-btn"),
  revokeStatus: document.getElementById("revoke-status"),
  keyList: document.getElementById("key-list"),
};

const renderTenantOptions = (tenants, selects, emptyMessage = "No tenants found") => {
  selects.forEach((select) => {
    if (!select) {
      return;
    }
    select.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = tenants.length ? "Select tenant" : emptyMessage;
    select.appendChild(placeholder);
    tenants.forEach((tenant) => {
      const option = document.createElement("option");
      option.value = tenant;
      option.textContent = tenant;
      select.appendChild(option);
    });
  });
};

const renderKeyNameOptions = (keys, select, emptyMessage = "No keys found") => {
  if (!select) {
    return;
  }
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = keys.length ? "Select key" : emptyMessage;
  select.appendChild(placeholder);
  keys.forEach((key) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = key;
    select.appendChild(option);
  });
};

const loadTenants = async () => {
  renderTenantOptions(
    [],
    [keyElements.keyTenant, keyElements.listTenant, keyElements.importTenant, keyElements.revokeTenant],
    "Loading..."
  );
  try {
    const result = await apiFetch("/v1/admin/tenants", { method: "GET" });
    const tenants = (result.tenants || []).map((t) => t.tenant).sort();
    renderTenantOptions(
      tenants,
      [keyElements.keyTenant, keyElements.listTenant, keyElements.importTenant, keyElements.revokeTenant]
    );
  } catch (err) {
    renderTenantOptions(
      [],
      [keyElements.keyTenant, keyElements.listTenant, keyElements.importTenant, keyElements.revokeTenant],
      "No session. Save admin key."
    );
  }
};

const loadKeyNamesForTenant = async (tenant, select, emptyMessage) => {
  if (!tenant) {
    renderKeyNameOptions([], select, emptyMessage);
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "GET",
    });
    const names = (result.keys || []).filter((k) => k.active).map((k) => k.name).sort();
    renderKeyNameOptions(names, select, emptyMessage);
  } catch (err) {
    renderKeyNameOptions([], select, emptyMessage);
  }
};

const runHealthCheck = async () => {
  setStatus(keyElements.sessionStatus, "Checking gateway health...", "info");
  if (keyElements.healthChip) {
    keyElements.healthChip.textContent = "Status: checking...";
  }
  try {
    const api = await healthFetch("/health");
    const ollama = await healthFetch("/health/ollama");
    const apiStatus = api.status || "ok";
    const ollamaStatus = ollama.status || "unknown";
    setStatus(
      keyElements.sessionStatus,
      `Health ok (api: ${apiStatus}, ollama: ${ollamaStatus}).`,
      "ok"
    );
    if (keyElements.healthChip) {
      keyElements.healthChip.textContent = `Status: ok (api: ${apiStatus}, ollama: ${ollamaStatus})`;
      keyElements.healthChip.dataset.state = "ok";
    }
  } catch (err) {
    setStatus(keyElements.sessionStatus, err.message, "error");
    if (keyElements.healthChip) {
      keyElements.healthChip.textContent = `Status: error (${err.message})`;
      keyElements.healthChip.dataset.state = "error";
    }
  }
};

keyElements.saveSettings?.addEventListener("click", async () => {
  saveSettings(keyElements.sessionStatus, keyElements.envPill);
  await runHealthCheck();
  await loadTenants();
});

keyElements.clearSettings?.addEventListener("click", () => {
  clearSettings(keyElements.sessionStatus, keyElements.envPill);
  renderKeyList(keyElements.keyList);
  if (keyElements.keyValue) {
    keyElements.keyValue.textContent = "No key generated yet.";
  }
  if (keyElements.copyLatest) {
    keyElements.copyLatest.disabled = true;
  }
  renderTenantOptions(
    [],
    [keyElements.keyTenant, keyElements.listTenant, keyElements.importTenant, keyElements.revokeTenant],
    "No session. Save admin key."
  );
  renderKeyNameOptions([], keyElements.importKeyName, "No session. Save admin key.");
  renderKeyNameOptions([], keyElements.revokeKeyName, "No session. Save admin key.");
});

keyElements.createKey?.addEventListener("click", async () => {
  const tenant = keyElements.keyTenant.value.trim();
  const name = keyElements.keyName.value.trim();
  if (!tenant) {
    setStatus(keyElements.sessionStatus, "Tenant name is required.", "warn");
    return;
  }
  if (!name) {
    setStatus(keyElements.sessionStatus, "Key name is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    keyElements.keyValue.textContent = result.api_key;
    keyElements.copyLatest.disabled = false;
    const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
    keys.unshift({
      tenant: result.tenant,
      name: result.name,
      apiKey: result.api_key,
      createdAt: Date.now(),
      active: true,
    });
    localStorage.setItem(KEYS_KEY, JSON.stringify(keys.slice(0, 12)));
    renderKeyList(keyElements.keyList);
    setStatus(keyElements.sessionStatus, `Key created for ${result.tenant}.`, "ok");
  } catch (err) {
    setStatus(keyElements.sessionStatus, err.message, "error");
  }
});

keyElements.copyLatest?.addEventListener("click", async () => {
  const text = keyElements.keyValue.textContent;
  if (!text || text.includes("No key")) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus(keyElements.sessionStatus, "Key copied to clipboard.", "ok");
  } catch (err) {
    setStatus(keyElements.sessionStatus, "Copy failed. Select the key manually.", "warn");
  }
});

keyElements.listKeys?.addEventListener("click", async () => {
  const tenant = keyElements.listTenant.value.trim();
  if (!tenant) {
    setStatus(keyElements.keysStatus, "Tenant name is required.", "warn");
    return;
  }
  keyElements.tenantKeys.innerHTML = "";
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "GET",
    });
    if (!result.keys.length) {
      keyElements.tenantKeys.innerHTML = "<div class=\"muted\">No keys for tenant.</div>";
    } else {
      result.keys.forEach((k) => {
        const div = document.createElement("div");
        div.className = "key-item";
        const created = k.created_at ? new Date(k.created_at).toLocaleString() : "unknown";
        const lastUsed = k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never";
        const state = k.active ? "active" : "revoked";
        const revokedNote = k.revoked_at
          ? `revoked: ${new Date(k.revoked_at).toLocaleString()}`
          : k.revoked_reason
            ? `revoked: ${k.revoked_reason}`
            : "";
        div.innerHTML = `
          <strong>${state.toUpperCase()} • ${k.name}</strong>
          <span>${created}</span>
          <span>last used: ${lastUsed}</span>
          ${revokedNote ? `<span>${revokedNote}</span>` : ""}
          <span class="pill">hash ****${k.key_last6}</span>
        `;
        if (!k.active) {
          div.classList.add("revoked");
        }
        keyElements.tenantKeys.appendChild(div);
      });
    }
    setStatus(keyElements.keysStatus, "Keys loaded.", "ok");
  } catch (err) {
    setStatus(keyElements.keysStatus, err.message, "error");
  }
});

keyElements.revokeKeyBtn?.addEventListener("click", async () => {
  const tenant = keyElements.revokeTenant.value.trim();
  const name = keyElements.revokeKeyName.value.trim();
  const reason = keyElements.revokeReason?.value.trim();
  if (!tenant || !name) {
    setStatus(keyElements.revokeStatus, "Tenant and key name are required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys/revoke`, {
      method: "POST",
      body: JSON.stringify({ name, reason: reason || null }),
    });
    const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
    const updated = keys.map((item) => {
      if (item.tenant === tenant && item.name === name) {
        return { ...item, active: false, revokedAt: Date.now(), revokedReason: reason || null };
      }
      return item;
    });
    localStorage.setItem(KEYS_KEY, JSON.stringify(updated));
    setStatus(
      keyElements.revokeStatus,
      result.tenant ? `Key revoked for ${result.tenant}.` : "Key revoked.",
      "ok"
    );
  } catch (err) {
    setStatus(keyElements.revokeStatus, err.message, "error");
  }
});

keyElements.importTenant?.addEventListener("change", () => {
  const tenant = keyElements.importTenant.value.trim();
  loadKeyNamesForTenant(tenant, keyElements.importKeyName, "No keys found");
});

keyElements.revokeTenant?.addEventListener("change", () => {
  const tenant = keyElements.revokeTenant.value.trim();
  loadKeyNamesForTenant(tenant, keyElements.revokeKeyName, "No keys found");
});

keyElements.importKeyBtn?.addEventListener("click", async () => {
  const tenant = keyElements.importTenant.value.trim();
  const name = keyElements.importKeyName.value.trim();
  const apiKey = keyElements.importKeyValue.value.trim();
  if (!tenant || !name || !apiKey) {
    setStatus(keyElements.importStatus, "Tenant, key name, and key value are required.", "warn");
    return;
  }
  try {
    const result = await apiFetch("/v1/admin/keys/verify", {
      method: "POST",
      body: JSON.stringify({ tenant, name, api_key: apiKey }),
    });
    if (!result.matches) {
      setStatus(keyElements.importStatus, "Key verification failed.", "error");
      return;
    }
    const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
    const updated = keys.filter((item) => !(item.tenant === tenant && item.name === name));
    updated.unshift({
      tenant,
      name,
      apiKey,
      createdAt: Date.now(),
      active: true,
    });
    localStorage.setItem(KEYS_KEY, JSON.stringify(updated.slice(0, 12)));
    renderKeyList(keyElements.keyList);
    setStatus(keyElements.importStatus, "Key verified and stored locally.", "ok");
  } catch (err) {
    setStatus(keyElements.importStatus, err.message, "error");
  }
});

loadSettings();
updateEnvPill(keyElements.envPill);
renderKeyList(keyElements.keyList);
loadTenants();
loadKeyNamesForTenant(keyElements.importTenant?.value || "", keyElements.importKeyName, "No keys found");
loadKeyNamesForTenant(keyElements.revokeTenant?.value || "", keyElements.revokeKeyName, "No keys found");
