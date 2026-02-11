const tenantElements = {
  envPill: document.getElementById("env-pill"),
  sessionStatus: document.getElementById("session-status"),
  saveSettings: document.getElementById("save-settings"),
  clearSettings: document.getElementById("clear-settings"),
  healthChip: document.getElementById("health-chip"),
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
  detailRevokeReason: document.getElementById("detail-revoke-reason"),
  detailRevoke: document.getElementById("detail-revoke"),
};

let selectedTenant = null;

const setSelectedTenant = (tenant) => {
  selectedTenant = tenant;
  tenantElements.detailName.textContent = tenant ? tenant.tenant : "No tenant selected";
  tenantElements.detailTier.textContent = `Tier: ${tenant ? tenant.tier : "--"}`;
  tenantElements.detailCreated.textContent = `Created: ${
    tenant?.created_at ? new Date(tenant.created_at).toLocaleString() : "--"
  }`;
  tenantElements.detailRequests.textContent = "--";
  tenantElements.detailTokens.textContent = "--";
  tenantElements.detailCost.textContent = "--";
  tenantElements.detailKeysList.innerHTML = "";
};

const renderTenants = (tenants) => {
  tenantElements.tenantsBody.innerHTML = "";
  if (!tenants.length) {
    tenantElements.tenantsBody.innerHTML = "<tr><td colspan=\"5\">No tenants found.</td></tr>";
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
    tenantElements.tenantsBody.appendChild(row);
  });
};

const runHealthCheck = async () => {
  setStatus(tenantElements.sessionStatus, "Checking gateway health...", "info");
  if (tenantElements.healthChip) {
    tenantElements.healthChip.textContent = "Status: checking...";
  }
  try {
    const api = await healthFetch("/health");
    const ollama = await healthFetch("/health/ollama");
    const apiStatus = api.status || "ok";
    const ollamaStatus = ollama.status || "unknown";
    setStatus(
      tenantElements.sessionStatus,
      `Health ok (api: ${apiStatus}, ollama: ${ollamaStatus}).`,
      "ok"
    );
    if (tenantElements.healthChip) {
      tenantElements.healthChip.textContent = `Status: ok (api: ${apiStatus}, ollama: ${ollamaStatus})`;
      tenantElements.healthChip.dataset.state = "ok";
    }
  } catch (err) {
    setStatus(tenantElements.sessionStatus, err.message, "error");
    if (tenantElements.healthChip) {
      tenantElements.healthChip.textContent = `Status: error (${err.message})`;
      tenantElements.healthChip.dataset.state = "error";
    }
  }
};

tenantElements.saveSettings?.addEventListener("click", async () => {
  saveSettings(tenantElements.sessionStatus, tenantElements.envPill);
  await runHealthCheck();
});

tenantElements.clearSettings?.addEventListener("click", () => {
  clearSettings(tenantElements.sessionStatus, tenantElements.envPill);
});

tenantElements.loadTenants?.addEventListener("click", async () => {
  try {
    const result = await apiFetch("/v1/admin/tenants", { method: "GET" });
    renderTenants(result.tenants || []);
    setSelectedTenant(null);
    setStatus(tenantElements.tenantsStatus, "Tenants loaded.", "ok");
  } catch (err) {
    setStatus(tenantElements.tenantsStatus, err.message, "error");
  }
});

tenantElements.detailUsage?.addEventListener("click", async () => {
  if (!selectedTenant) {
    setStatus(tenantElements.detailStatus, "Select a tenant first.", "warn");
    return;
  }
  try {
    const result = await apiFetch(`/v1/admin/usage/${encodeURIComponent(selectedTenant.tenant)}`, {
      method: "GET",
    });
    tenantElements.detailRequests.textContent = result.requests;
    tenantElements.detailTokens.textContent = result.tokens;
    tenantElements.detailCost.textContent = Number(result.cost_usd || 0).toFixed(4);
    setStatus(tenantElements.detailStatus, "Usage loaded.", "ok");
  } catch (err) {
    setStatus(tenantElements.detailStatus, err.message, "error");
  }
});

tenantElements.detailKeys?.addEventListener("click", async () => {
  if (!selectedTenant) {
    setStatus(tenantElements.detailStatus, "Select a tenant first.", "warn");
    return;
  }
  tenantElements.detailKeysList.innerHTML = "";
  try {
    const result = await apiFetch(
      `/v1/admin/tenants/${encodeURIComponent(selectedTenant.tenant)}/keys`,
      { method: "GET" }
    );
    if (!result.keys.length) {
      tenantElements.detailKeysList.innerHTML = "<div class=\"muted\">No keys for tenant.</div>";
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
        tenantElements.detailKeysList.appendChild(div);
      });
    }
    setStatus(tenantElements.detailStatus, "Keys loaded.", "ok");
  } catch (err) {
    setStatus(tenantElements.detailStatus, err.message, "error");
  }
});

tenantElements.detailRevoke?.addEventListener("click", async () => {
  const name = tenantElements.detailRevokeInput.value.trim();
  const reason = tenantElements.detailRevokeReason?.value.trim();
  if (!selectedTenant) {
    setStatus(tenantElements.detailStatus, "Select a tenant first.", "warn");
    return;
  }
  if (!name) {
    setStatus(tenantElements.detailStatus, "Key name is required.", "warn");
    return;
  }
  try {
    const result = await apiFetch(
      `/v1/admin/tenants/${encodeURIComponent(selectedTenant.tenant)}/keys/revoke`,
      {
      method: "POST",
      body: JSON.stringify({ name, reason: reason || null }),
    }
    );
    setStatus(
      tenantElements.detailStatus,
      result.tenant ? `Key revoked for ${result.tenant}.` : "Key revoked.",
      "ok"
    );
  } catch (err) {
    setStatus(tenantElements.detailStatus, err.message, "error");
  }
});

loadSettings();
updateEnvPill(tenantElements.envPill);
