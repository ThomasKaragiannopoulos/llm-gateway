const adminElements = {
  envPill: document.getElementById("env-pill"),
  sessionStatus: document.getElementById("session-status"),
  saveSettings: document.getElementById("save-settings"),
  clearSettings: document.getElementById("clear-settings"),
  healthChip: document.getElementById("health-chip"),
  rotateAdmin: document.getElementById("rotate-admin"),
  copyAdmin: document.getElementById("copy-admin"),
  adminKeyValue: document.getElementById("admin-key-value"),
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

loadSettings();
updateEnvPill(adminElements.envPill);

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
