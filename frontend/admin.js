const adminElements = {
  envPill: document.getElementById("env-pill"),
  sessionStatus: document.getElementById("session-status"),
  saveSettings: document.getElementById("save-settings"),
  clearSettings: document.getElementById("clear-settings"),
  healthChip: document.getElementById("health-chip"),
  tenantName: document.getElementById("tenant-name"),
  tenantTier: document.getElementById("tenant-tier"),
  createTenant: document.getElementById("create-tenant"),
  tenantStatus: document.getElementById("tenant-status"),
  keyTenant: document.getElementById("key-tenant"),
  keyName: document.getElementById("key-name"),
  createKey: document.getElementById("create-key"),
  keyValue: document.getElementById("key-value"),
  copyLatest: document.getElementById("copy-latest"),
  listTenant: document.getElementById("list-tenant"),
  listKeys: document.getElementById("list-keys"),
  tenantKeys: document.getElementById("tenant-keys"),
  keysStatus: document.getElementById("keys-status"),
  rotateAdmin: document.getElementById("rotate-admin"),
  copyAdmin: document.getElementById("copy-admin"),
  adminKeyValue: document.getElementById("admin-key-value"),
  revokeTenant: document.getElementById("revoke-tenant"),
  revokeKeyName: document.getElementById("revoke-key-name"),
  revokeReason: document.getElementById("revoke-reason"),
  revokeKeyBtn: document.getElementById("revoke-key-btn"),
  revokeStatus: document.getElementById("revoke-status"),
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
  keyList: document.getElementById("key-list"),
  loadAudit: document.getElementById("load-audit"),
  auditBody: document.getElementById("audit-body"),
  auditStatus: document.getElementById("audit-status"),
};

const runHealthCheck = async () => {
  setStatus(adminElements.sessionStatus, "Checking gateway health...", "info");
  if (adminElements.healthChip) {
    adminElements.healthChip.textContent = "Status: checking...";
  }
  try {
    const api = await healthFetch("/health");
    const ollama = await healthFetch("/health/ollama");
    const apiStatus = api.status || "ok";
    const ollamaStatus = ollama.status || "unknown";
    setStatus(
      adminElements.sessionStatus,
      `Health ok (api: ${apiStatus}, ollama: ${ollamaStatus}).`,
      "ok"
    );
    if (adminElements.healthChip) {
      adminElements.healthChip.textContent = `Status: ok (api: ${apiStatus}, ollama: ${ollamaStatus})`;
      adminElements.healthChip.dataset.state = "ok";
    }
  } catch (err) {
    setStatus(adminElements.sessionStatus, err.message, "error");
    if (adminElements.healthChip) {
      adminElements.healthChip.textContent = `Status: error (${err.message})`;
      adminElements.healthChip.dataset.state = "error";
    }
  }
};

adminElements.saveSettings?.addEventListener("click", async () => {
  saveSettings(adminElements.sessionStatus, adminElements.envPill);
  await runHealthCheck();
});

adminElements.clearSettings?.addEventListener("click", () => {
  clearSettings(adminElements.sessionStatus, adminElements.envPill);
  renderKeyList(adminElements.keyList);
  if (adminElements.keyValue) {
    adminElements.keyValue.textContent = "No key generated yet.";
  }
  if (adminElements.copyLatest) {
    adminElements.copyLatest.disabled = true;
  }
});

adminElements.createTenant?.addEventListener("click", async () => {
  const tenant = adminElements.tenantName.value.trim();
  if (!tenant) {
    setStatus(adminElements.tenantStatus, "Tenant name is required.", "warn");
    return;
  }
  const tier = adminElements.tenantTier.value.trim();
  try {
    const result = await apiFetch("/v1/admin/tenants", {
      method: "POST",
      body: JSON.stringify({ tenant, tier: tier || null }),
    });
    setStatus(adminElements.tenantStatus, `Tenant ${result.tenant} created (${result.tier}).`, "ok");
  } catch (err) {
    setStatus(adminElements.tenantStatus, err.message, "error");
  }
});

adminElements.createKey?.addEventListener("click", async () => {
  const tenant = adminElements.keyTenant.value.trim();
  const name = adminElements.keyName.value.trim();
  if (!tenant) {
    setStatus(adminElements.sessionStatus, "Tenant name is required.", "warn");
    return;
  }
  if (!name) {
    setStatus(adminElements.sessionStatus, "Key name is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    adminElements.keyValue.textContent = result.api_key;
    adminElements.copyLatest.disabled = false;
    const keys = JSON.parse(localStorage.getItem(KEYS_KEY) || "[]");
    keys.unshift({ tenant: result.tenant, name: result.name, apiKey: result.api_key, createdAt: Date.now() });
    localStorage.setItem(KEYS_KEY, JSON.stringify(keys.slice(0, 12)));
    renderKeyList(adminElements.keyList);
    setStatus(adminElements.sessionStatus, `Key created for ${result.tenant}.`, "ok");
  } catch (err) {
    setStatus(adminElements.sessionStatus, err.message, "error");
  }
});

adminElements.copyLatest?.addEventListener("click", async () => {
  const text = adminElements.keyValue.textContent;
  if (!text || text.includes("No key")) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus(adminElements.sessionStatus, "Key copied to clipboard.", "ok");
  } catch (err) {
    setStatus(adminElements.sessionStatus, "Copy failed. Select the key manually.", "warn");
  }
});

adminElements.listKeys?.addEventListener("click", async () => {
  const tenant = adminElements.listTenant.value.trim();
  if (!tenant) {
    setStatus(adminElements.keysStatus, "Tenant name is required.", "warn");
    return;
  }
  adminElements.tenantKeys.innerHTML = "";
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys`, {
      method: "GET",
    });
    if (!result.keys.length) {
      adminElements.tenantKeys.innerHTML = "<div class=\"muted\">No keys for tenant.</div>";
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
        adminElements.tenantKeys.appendChild(div);
      });
    }
    setStatus(adminElements.keysStatus, "Keys loaded.", "ok");
  } catch (err) {
    setStatus(adminElements.keysStatus, err.message, "error");
  }
});

adminElements.rotateAdmin?.addEventListener("click", async () => {
  try {
    const result = await apiFetch("/v1/admin/keys/rotate", { method: "POST" });
    adminElements.adminKeyValue.textContent = result.admin_api_key;
    adminElements.copyAdmin.disabled = false;
    const baseUrlInput = document.getElementById("base-url");
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ baseUrl: baseUrlInput ? baseUrlInput.value.trim() : "", adminKey: result.admin_api_key })
    );
    const adminKeyInput = document.getElementById("admin-key");
    if (adminKeyInput) {
      adminKeyInput.value = result.admin_api_key;
    }
    setStatus(
      adminElements.sessionStatus,
      "Admin key rotated. Update ADMIN_API_KEY and restart to persist.",
      "warn"
    );
  } catch (err) {
    setStatus(adminElements.sessionStatus, err.message, "error");
  }
});

adminElements.copyAdmin?.addEventListener("click", async () => {
  const text = adminElements.adminKeyValue.textContent;
  if (!text || text.includes("No rotation")) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus(adminElements.sessionStatus, "Admin key copied to clipboard.", "ok");
  } catch (err) {
    setStatus(adminElements.sessionStatus, "Copy failed. Select the key manually.", "warn");
  }
});

adminElements.revokeKeyBtn?.addEventListener("click", async () => {
  const tenant = adminElements.revokeTenant.value.trim();
  const name = adminElements.revokeKeyName.value.trim();
  const reason = adminElements.revokeReason?.value.trim();
  if (!tenant || !name) {
    setStatus(adminElements.revokeStatus, "Tenant and key name are required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenant)}/keys/revoke`, {
      method: "POST",
      body: JSON.stringify({ name, reason: reason || null }),
    });
    setStatus(
      adminElements.revokeStatus,
      result.tenant ? `Key revoked for ${result.tenant}.` : "Key revoked.",
      "ok"
    );
  } catch (err) {
    setStatus(adminElements.revokeStatus, err.message, "error");
  }
});

adminElements.setLimits?.addEventListener("click", async () => {
  const tenant = adminElements.limitsTenant.value.trim();
  if (!tenant) {
    setStatus(adminElements.limitsStatus, "Tenant name is required.", "warn");
    return;
  }
  const tokenValue = adminElements.tokenLimit.value.trim();
  const spendValue = adminElements.spendLimit.value.trim();
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
    setStatus(adminElements.limitsStatus, "Limits updated.", "ok");
  } catch (err) {
    setStatus(adminElements.limitsStatus, err.message, "error");
  }
});

adminElements.fetchUsage?.addEventListener("click", async () => {
  const tenant = adminElements.usageTenant.value.trim();
  if (!tenant) {
    setStatus(adminElements.usageStatus, "Tenant name is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/usage/${encodeURIComponent(tenant)}`, {
      method: "GET",
    });
    adminElements.usageRequests.textContent = result.requests;
    adminElements.usageTokens.textContent = result.tokens;
    adminElements.usageCost.textContent = Number(result.cost_usd || 0).toFixed(4);
    setStatus(adminElements.usageStatus, "Usage loaded.", "ok");
  } catch (err) {
    setStatus(adminElements.usageStatus, err.message, "error");
  }
});

loadSettings();
updateEnvPill(adminElements.envPill);
renderKeyList(adminElements.keyList);

adminElements.loadAudit?.addEventListener("click", async () => {
  try {
    const result = await apiFetch("/v1/admin/audit", { method: "GET" });
    adminElements.auditBody.innerHTML = "";
    if (!result.actions.length) {
      adminElements.auditBody.innerHTML = "<tr><td colspan=\"5\">No audit events.</td></tr>";
    } else {
      result.actions.forEach((entry) => {
        const row = document.createElement("tr");
        const created = entry.created_at ? new Date(entry.created_at).toLocaleString() : "--";
        const target = entry.target_id ? `${entry.target_type}:${entry.target_id}` : entry.target_type;
        const meta = entry.metadata ? JSON.stringify(entry.metadata) : "--";
        row.innerHTML = `
          <td>${created}</td>
          <td>${entry.actor}</td>
          <td>${entry.action}</td>
          <td>${target}</td>
          <td>${meta}</td>
        `;
        adminElements.auditBody.appendChild(row);
      });
    }
    setStatus(adminElements.auditStatus, "Audit log loaded.", "ok");
  } catch (err) {
    setStatus(adminElements.auditStatus, err.message, "error");
  }
});
