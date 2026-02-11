import { useEffect, useMemo, useState } from "react";

type ErrorDetail = { code: string; message: string };

type ApiKeyEntry = {
  id: string;
  name: string | null;
  tenant: string;
  active: boolean;
  created_at: string;
};

function useLocalStorage(key: string, initialValue: string) {
  const [value, setValue] = useState(() => {
    const stored = window.localStorage.getItem(key);
    return stored ?? initialValue;
  });

  const setAndStore = (next: string) => {
    setValue(next);
    if (next) {
      window.localStorage.setItem(key, next);
    } else {
      window.localStorage.removeItem(key);
    }
  };

  return [value, setAndStore] as const;
}

export default function App() {
  const [storedKeysRaw, setStoredKeysRaw] = useLocalStorage(
    "llm_gateway_api_keys",
    "[]"
  );
  const [adminKey, setAdminKey] = useLocalStorage("llm_gateway_admin_key", "");
  const [lastGeneratedKey, setLastGeneratedKey] = useLocalStorage(
    "llm_gateway_last_api_key",
    ""
  );
  const [model] = useLocalStorage("llm_gateway_model", "mock-1");
  const [apiKeysReady, setApiKeysReady] = useState(false);
  const [apiKeyName, setApiKeyName] = useState("");
  const [apiKeys, setApiKeys] = useState<ApiKeyEntry[]>([]);
  const [apiKeysError, setApiKeysError] = useState<string | null>(null);
  const [apiKeysLoading, setApiKeysLoading] = useState(false);
  const [bootstrapKey, setBootstrapKey] = useState<string | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [rotateError, setRotateError] = useState<string | null>(null);
  const [pricingMap, setPricingMap] = useState<
    Record<string, { input: number; output: number; cached: number }>
  >({});
  const [pricingForm, setPricingForm] = useState({
    input: 0,
    output: 0,
    cached: 0
  });
  const [pricingSaved, setPricingSaved] = useState(false);
  const [pricingError, setPricingError] = useState<string | null>(null);
  const [adminInitialized, setAdminInitialized] = useState<boolean | null>(null);

  const baseUrl = useMemo(() => {
    return import.meta.env.VITE_GATEWAY_URL || "http://localhost:8000";
  }, []);


  const readError = async (res: Response): Promise<ErrorDetail> => {
    const fallback = {
      code: "request_failed",
      message: `Request failed (${res.status})`
    };

    try {
      const data = (await res.json()) as { error?: ErrorDetail };
      if (data?.error) {
        return data.error;
      }
    } catch {
      return fallback;
    }
    return fallback;
  };

  const adminConfigured = Boolean(adminKey.trim());
  const storedKeys: { name: string; key: string }[] = useMemo(() => {
    try {
      const parsed = JSON.parse(storedKeysRaw) as { name: string; key: string }[];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }, [storedKeysRaw]);
  const retrievableKeyNames = useMemo(() => {
    return new Set(storedKeys.map((entry) => entry.name));
  }, [storedKeys]);

  const callAdmin = async <T,>(path: string, body?: Record<string, unknown>) => {
    if (!adminKey) {
      setApiKeysError("Generate an admin key first.");
      return null;
    }
    setBootstrapError(null);
    setRotateError(null);
    setApiKeysError(null);
    setPricingError(null);

    const res = await fetch(`${baseUrl}${path}`, {
      method: body ? "POST" : "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${adminKey}`
      },
      body: body ? JSON.stringify(body) : undefined
    });

    if (!res.ok) {
      const err = await readError(res);
      setApiKeysError(`${err.code}: ${err.message}`);
      return null;
    }

    return (await res.json()) as T;
  };

  const loadPricing = async () => {
    if (!adminKey) {
      return;
    }
    setPricingError(null);
    try {
      const res = await fetch(`${baseUrl}/v1/admin/pricing`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${adminKey}`
        }
      });
      if (!res.ok) {
        const err = await readError(res);
        setPricingError(`${err.code}: ${err.message}`);
        return;
      }
      const data = (await res.json()) as {
        items: { model: string; input_per_1k: number; output_per_1k: number; cached_per_1k: number }[];
      };
      const next: Record<string, { input: number; output: number; cached: number }> = {};
      data.items.forEach((item) => {
        next[item.model] = {
          input: Number(item.input_per_1k),
          output: Number(item.output_per_1k),
          cached: Number(item.cached_per_1k)
        };
      });
      setPricingMap(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setPricingError(message);
    }
  };

  const savePricing = async () => {
    if (!adminKey) {
      setPricingError("Generate an admin key first.");
      return;
    }
    setPricingError(null);
    setPricingSaved(false);
    const items = [
      {
        model,
        input_per_1k: Number(pricingForm.input),
        output_per_1k: Number(pricingForm.output),
        cached_per_1k: Number(pricingForm.cached)
      }
    ];
    try {
      const res = await fetch(`${baseUrl}/v1/admin/pricing`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${adminKey}`
        },
        body: JSON.stringify({ items })
      });
      if (!res.ok) {
        const err = await readError(res);
        setPricingError(`${err.code}: ${err.message}`);
        return;
      }
      setPricingSaved(true);
      setPricingMap((prev) => ({
        ...prev,
        [model]: { ...pricingForm }
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setPricingError(message);
    }
  };

  const bootstrapAdminKey = async () => {
    setBootstrapError(null);
    setBootstrapKey(null);
    setRotateError(null);
    try {
      const res = await fetch(`${baseUrl}/v1/admin/bootstrap`, {
        method: "POST"
      });
      if (!res.ok) {
        const err = await readError(res);
        setBootstrapError(`${err.code}: ${err.message}`);
        return;
      }
      const data = (await res.json()) as { api_key: string };
      setBootstrapKey(data.api_key);
      setAdminKey(data.api_key);
      setBootstrapError(null);
      setRotateError(null);
      setLastGeneratedKey("");
      await refreshApiKeys(data.api_key);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setBootstrapError(message);
    }
  };

  const rotateAdminKey = async () => {
    setRotateError(null);
    setBootstrapKey(null);
    try {
      const res = await fetch(`${baseUrl}/v1/admin/rotate`, {
        method: "POST"
      });
      if (!res.ok) {
        const err = await readError(res);
        setRotateError(`${err.code}: ${err.message}`);
        return;
      }
      const data = (await res.json()) as { api_key: string };
      setBootstrapKey(data.api_key);
      setAdminKey(data.api_key);
      setBootstrapError(null);
      setRotateError(null);
      setLastGeneratedKey("");
      await refreshApiKeys(data.api_key);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setRotateError(message);
    }
  };

  const refreshApiKeys = async (overrideAdminKey?: string, silent?: boolean) => {
    const keyToUse = overrideAdminKey ?? adminKey;
    if (!keyToUse) {
      return false;
    }
    setApiKeysLoading(true);
    if (!silent) {
      setApiKeysError(null);
    }
    try {
      const res = await fetch(`${baseUrl}/v1/admin/keys`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${keyToUse}`
        }
      });
      if (!res.ok) {
        const err = await readError(res);
        if (!silent) {
          setApiKeysError(`${err.code}: ${err.message}`);
        }
        if (!silent) {
          setApiKeys([]);
        }
        if (res.status === 401 || res.status === 403) {
          setApiKeysReady(true);
          const autoKeyFlag = "llm_gateway_auto_bootstrap_done";
          if (!window.sessionStorage.getItem(autoKeyFlag)) {
            window.sessionStorage.setItem(autoKeyFlag, "true");
            try {
              const bootstrapRes = await fetch(`${baseUrl}/v1/admin/bootstrap`, {
                method: "POST"
              });
                if (bootstrapRes.ok) {
                  const data = (await bootstrapRes.json()) as { api_key: string };
                  setAdminKey(data.api_key);
                  setBootstrapKey(data.api_key);
                  setLastGeneratedKey("");
                  setApiKeysError(null);
                  return await refreshApiKeys(data.api_key, true);
                }
            } catch {
              // fall through to show invalid key message
            }
          }
          setAdminKey("");
          setApiKeys([]);
          setApiKeysError("Admin key is invalid. Generate a new admin key.");
        }
        setApiKeysLoading(false);
        return false;
      }
      const data = (await res.json()) as { keys: ApiKeyEntry[] };
      setApiKeys(data.keys);
      setApiKeysError(null);
      setApiKeysReady(true);
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      if (!silent) {
        setApiKeysError(message);
      }
      return false;
    } finally {
      setApiKeysLoading(false);
    }
  };

  const createApiKey = async () => {
    if (!adminKey) {
      setApiKeysError("Generate an admin key first.");
      return;
    }
    if (!apiKeyName.trim()) {
      setApiKeysError("Provide a name for the API key.");
      return;
    }
    const payload = await callAdmin<{ api_key: string; tenant: string }>("/v1/admin/keys", {
      name: apiKeyName.trim()
    });
    if (payload) {
      setLastGeneratedKey(payload.api_key);
      const next = [
        ...storedKeys.filter((entry) => entry.name !== payload.tenant),
        { name: payload.tenant, key: payload.api_key }
      ];
      setStoredKeysRaw(JSON.stringify(next));
      setApiKeyName("");
      await refreshApiKeys();
    }
  };

  const deleteApiKey = async (id: string) => {
    if (!adminKey) {
      return;
    }
    setApiKeysError(null);
    const res = await fetch(`${baseUrl}/v1/admin/keys/${id}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${adminKey}`
      }
    });
    if (!res.ok) {
      const err = await readError(res);
      setApiKeysError(`${err.code}: ${err.message}`);
      return;
    }
    await refreshApiKeys();
  };

  const topErrors = [bootstrapError, rotateError, apiKeysError, pricingError].filter(
    Boolean
  ) as string[];

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    let attempt = 0;
    const maxAttempts = 5;

    const run = async () => {
      attempt += 1;
      try {
        const res = await fetch(`${baseUrl}/v1/admin/status`, { method: "GET" });
        if (!res.ok) {
          throw new Error(`status ${res.status}`);
        }
        const data = (await res.json()) as { admin_initialized?: boolean };
        if (cancelled) {
          return;
        }
        if (typeof data.admin_initialized === "boolean") {
          setAdminInitialized(data.admin_initialized);
          if (data.admin_initialized === false && !adminKey) {
            await bootstrapAdminKey();
          }
        } else {
          setAdminInitialized(null);
        }
      } catch {
        if (cancelled) {
          return;
        }
        if (attempt < maxAttempts) {
          const delayMs = Math.min(2000, 300 * attempt);
          timer = window.setTimeout(run, delayMs);
        } else {
          setAdminInitialized(null);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [baseUrl]);

  useEffect(() => {
    if (!adminKey || !apiKeysReady) {
      return;
    }
    const payload = {
      displayed_count: apiKeys.filter((key) => key.active).length
    };
    fetch(`${baseUrl}/v1/ui/keys/telemetry`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${adminKey}`
      },
      body: JSON.stringify(payload)
    }).catch(() => {
      // best-effort telemetry
    });
  }, [adminKey, apiKeys, apiKeysReady, baseUrl]);

  useEffect(() => {
    if (adminKey) {
      setApiKeysReady(false);
      refreshApiKeys(undefined, true);
      loadPricing();
    } else {
      setApiKeys([]);
      setApiKeysError(null);
      setApiKeysReady(true);
    }
  }, [adminKey]);


  useEffect(() => {
    const existing = pricingMap[model];
    if (existing) {
      setPricingForm({ ...existing });
    } else {
      setPricingForm({ input: 0, output: 0, cached: 0 });
    }
    setPricingSaved(false);
  }, [model, pricingMap]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span>Developer Portal</span>
          <h1>LLM Gateway</h1>
        </div>
        <div style={{ marginTop: 24, display: "grid", gap: 8 }}>
          <div className="pill">Gateway: {baseUrl}</div>
        </div>
      </aside>
      <main className="main">
        <div className="header">
          <h2>Keys</h2>
        </div>
        {topErrors.length > 0 && (
          <div className="card" style={{ marginBottom: 20 }}>
            {topErrors.map((message) => (
              <div className="banner error" key={message} style={{ marginBottom: 8 }}>
                {message}
              </div>
            ))}
          </div>
        )}

        <div className="grid">
          <div className="card">
            <h3>Credentials</h3>
            {adminInitialized === false && (
              <div className="banner warning" style={{ marginBottom: 12 }}>
                No admin key found in the database. Click Generate to create one.
              </div>
            )}
            {adminInitialized === true && !adminConfigured && (
              <div className="banner warning" style={{ marginBottom: 12 }}>
                Admin key exists in the database. Enter it or rotate to continue.
              </div>
            )}
            <div className="form">
              <div className="field">
                <label>Admin API Key</label>
                <div className="row">
                  <input value={adminKey} readOnly />
                  <button
                    className="button secondary"
                    onClick={adminConfigured ? rotateAdminKey : bootstrapAdminKey}
                    type="button"
                  >
                    {adminConfigured ? "Rotate" : "Generate"}
                  </button>
                </div>
                {bootstrapKey && (
                  <div className="banner success" style={{ marginTop: 8 }}>
                    Admin key generated: <span className="value">{bootstrapKey}</span>
                  </div>
                )}
              </div>
              <div className="field">
                <label>API Key Name</label>
                <div className="row">
                  <input
                    value={apiKeyName}
                    onChange={(e) => setApiKeyName(e.target.value)}
                    placeholder="e.g. frontend"
                  />
                  <button className="button" onClick={createApiKey} type="button">
                    Generate
                  </button>
                </div>
                {lastGeneratedKey && (
                  <div className="banner success" style={{ marginTop: 8 }}>
                    API key generated: <span className="value">{lastGeneratedKey}</span>
                  </div>
                )}
              </div>
              <div className="field">
                <label>API Keys</label>
                <div className="row" style={{ marginBottom: 12, columnGap: 16 }}>
                  <div>
                    <div className="pill">DB Keys</div>
                    <div className="value">{apiKeys.length}</div>
                  </div>
                  <div>
                    <div className="pill">Displayed</div>
                    <div className="value">{apiKeys.filter((key) => key.active).length}</div>
                  </div>
                </div>
                <div className="row" style={{ marginBottom: 12, columnGap: 16 }}>
                  <div>
                    <div className="pill">Admin Key</div>
                    <div className="value">{adminKey || "-"}</div>
                  </div>
                  <div>
                    <div className="pill">Last Generated API Key</div>
                    <div className="value">{lastGeneratedKey || "-"}</div>
                  </div>
                </div>
                {apiKeysLoading && <div className="value">Loading keys...</div>}
                {!apiKeysLoading && apiKeys.length === 0 && (
                  <div className="value">No API keys yet.</div>
                )}
                {!apiKeysLoading && apiKeys.length > 0 && (
                  <div className="grid">
                    {apiKeys.map((key) => {
                      const keyName = key.name ?? key.tenant;
                      const retrievable = retrievableKeyNames.has(keyName);
                      return (
                      <div className="card" key={key.id}>
                        <div className="row" style={{ columnGap: 16 }}>
                          <div>
                            <div className="pill">Name</div>
                            <div className="value">{keyName}</div>
                          </div>
                          <div>
                            <div className="pill">Status</div>
                            <div className="row" style={{ columnGap: 12, alignItems: "center" }}>
                              <div className="value">{key.active ? "active" : "disabled"}</div>
                              {key.active && (
                                <button
                                  className="button secondary"
                                  onClick={() => deleteApiKey(key.id)}
                                  type="button"
                                >
                                  Disable
                                </button>
                              )}
                            </div>
                          </div>
                          <div>
                            <div className="pill">Retrievable</div>
                            <div className="value">{retrievable ? "yes" : "no"}</div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="card">
            <h3>Model Pricing</h3>
            <div className="form">
              <div className="field">
                <label>Model</label>
                <input value={model} readOnly />
              </div>
              <div className="row">
                <div className="field">
                  <label>Input / 1K</label>
                  <input
                    value={pricingForm.input}
                    onChange={(e) =>
                      setPricingForm((prev) => ({
                        ...prev,
                        input: Number(e.target.value)
                      }))
                    }
                  />
                </div>
                <div className="field">
                  <label>Output / 1K</label>
                  <input
                    value={pricingForm.output}
                    onChange={(e) =>
                      setPricingForm((prev) => ({
                        ...prev,
                        output: Number(e.target.value)
                      }))
                    }
                  />
                </div>
                <div className="field">
                  <label>Cached / 1K</label>
                  <input
                    value={pricingForm.cached}
                    onChange={(e) =>
                      setPricingForm((prev) => ({
                        ...prev,
                        cached: Number(e.target.value)
                      }))
                    }
                  />
                </div>
              </div>
              <div className="row">
                <button className="button" onClick={savePricing} type="button">
                  Save Pricing
                </button>
                {pricingSaved && <div className="pill">Saved</div>}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
