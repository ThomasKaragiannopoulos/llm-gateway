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
  ragEnabled: document.getElementById("rag-enabled"),
  ragTopK: document.getElementById("rag-topk"),
  ragMaxContext: document.getElementById("rag-max-context"),
  ragRerank: document.getElementById("rag-rerank"),
  ragLoad: document.getElementById("rag-load"),
  ragSave: document.getElementById("rag-save"),
  ragStatus: document.getElementById("rag-status"),
  ragTenant: document.getElementById("rag-tenant"),
  ragSource: document.getElementById("rag-source"),
  ragSourceId: document.getElementById("rag-source-id"),
  ragTitle: document.getElementById("rag-title"),
  ragChunkSize: document.getElementById("rag-chunk-size"),
  ragOverlap: document.getElementById("rag-overlap"),
  ragContent: document.getElementById("rag-content"),
  ragIngest: document.getElementById("rag-ingest"),
  ragIngestStatus: document.getElementById("rag-ingest-status"),
  evalDataset: document.getElementById("eval-dataset"),
  evalMinAccuracy: document.getElementById("eval-min-accuracy"),
  evalMaxP95: document.getElementById("eval-max-p95"),
  evalMaxCost: document.getElementById("eval-max-cost"),
  evalRun: document.getElementById("eval-run"),
  evalStatus: document.getElementById("eval-status"),
  evalOutput: document.getElementById("eval-output"),
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
    if (err?.status === 401) {
      setStatus(adminElements.sessionStatus, "Invalid admin key.", "error");
      return;
    }
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

const loadTenantOptions = async () => {
  if (!adminElements.ragTenant) {
    return;
  }
  adminElements.ragTenant.innerHTML = "";
  try {
    const result = await apiFetch("/v1/admin/tenants", { method: "GET" });
    const tenants = result.tenants || [];
    if (!tenants.length) {
      const option = document.createElement("option");
      option.value = "default";
      option.textContent = "default";
      adminElements.ragTenant.appendChild(option);
      return;
    }
    tenants.forEach((tenant) => {
      const option = document.createElement("option");
      option.value = tenant.tenant;
      option.textContent = `${tenant.tenant} (${tenant.tier})`;
      adminElements.ragTenant.appendChild(option);
    });
  } catch (err) {
    const option = document.createElement("option");
    option.value = "default";
    option.textContent = "default";
    adminElements.ragTenant.appendChild(option);
    setStatus(adminElements.ragIngestStatus, "Failed to load tenants; defaulting.", "warn");
  }
};

const loadRagSettings = async () => {
  try {
    const result = await apiFetch("/v1/admin/rag/settings", { method: "GET" });
    if (adminElements.ragEnabled) {
      adminElements.ragEnabled.checked = Boolean(result.enabled);
    }
    if (adminElements.ragTopK) {
      adminElements.ragTopK.value = result.top_k;
    }
    if (adminElements.ragMaxContext) {
      adminElements.ragMaxContext.value = result.max_context_chars;
    }
    if (adminElements.ragRerank) {
      adminElements.ragRerank.checked = Boolean(result.rerank);
    }
    setStatus(adminElements.ragStatus, "RAG settings loaded.", "ok");
  } catch (err) {
    setStatus(adminElements.ragStatus, err.message, "error");
  }
};

adminElements.ragLoad?.addEventListener("click", loadRagSettings);

adminElements.ragSave?.addEventListener("click", async () => {
  try {
    const payload = {
      enabled: Boolean(adminElements.ragEnabled?.checked),
      top_k: Number(adminElements.ragTopK?.value || 4),
      max_context_chars: Number(adminElements.ragMaxContext?.value || 4000),
      rerank: Boolean(adminElements.ragRerank?.checked),
    };
    const result = await apiFetch("/v1/admin/rag/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setStatus(adminElements.ragStatus, `RAG settings updated (enabled: ${result.enabled}).`, "ok");
  } catch (err) {
    setStatus(adminElements.ragStatus, err.message, "error");
  }
});

adminElements.ragIngest?.addEventListener("click", async () => {
  try {
    const content = adminElements.ragContent?.value.trim();
    if (!content) {
      setStatus(adminElements.ragIngestStatus, "Content is required.", "warn");
      return;
    }
    const payload = {
      tenant: adminElements.ragTenant?.value || "default",
      source: adminElements.ragSource?.value.trim() || "ui",
      source_id: adminElements.ragSourceId?.value.trim() || null,
      title: adminElements.ragTitle?.value.trim() || null,
      content,
      chunk_size: Number(adminElements.ragChunkSize?.value || 1000),
      overlap: Number(adminElements.ragOverlap?.value || 200),
    };
    const result = await apiFetch("/v1/admin/rag/ingest", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setStatus(
      adminElements.ragIngestStatus,
      `Ingested ${result.chunks} chunks for document ${result.document_id}.`,
      "ok"
    );
  } catch (err) {
    setStatus(adminElements.ragIngestStatus, err.message, "error");
  }
});

adminElements.evalRun?.addEventListener("click", async () => {
  try {
    const payload = {
      dataset_path: adminElements.evalDataset?.value.trim() || "evals/dataset.jsonl",
      min_accuracy: Number(adminElements.evalMinAccuracy?.value || 0.6),
      max_p95_latency_ms: Number(adminElements.evalMaxP95?.value || 2000),
      max_avg_cost_usd: Number(adminElements.evalMaxCost?.value || 0.01),
    };
    const result = await apiFetch("/v1/admin/evals/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (adminElements.evalOutput) {
      adminElements.evalOutput.textContent = JSON.stringify(result.summary, null, 2);
    }
    setStatus(adminElements.evalStatus, "Eval run complete.", "ok");
  } catch (err) {
    if (adminElements.evalOutput) {
      adminElements.evalOutput.textContent = "";
    }
    setStatus(adminElements.evalStatus, err.message, "error");
  }
});

loadRagSettings();
loadTenantOptions();

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
