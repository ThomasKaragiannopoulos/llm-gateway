import { useEffect, useMemo, useRef, useState } from "react";

type ErrorDetail = { code: string; message: string };

type Usage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
};

type StreamPayload = {
  id?: string;
  model?: string;
  created?: number;
  content?: string;
  done?: boolean;
  usage?: Usage;
  provider?: string;
  error?: ErrorDetail;
};

type HeaderMeta = {
  requestId: string | null;
  modelChosen: string | null;
  provider: string | null;
  routeReason: string | null;
  cache: string | null;
  retryAfter: string | null;
  tokensRemaining: string | null;
  spendRemaining: string | null;
};

type UsageMeta = {
  promptTokens: number | null;
  completionTokens: number | null;
  totalTokens: number | null;
  costUsd: number | null;
};

type ApiKeyEntry = {
  id: string;
  name: string | null;
  tenant: string;
  active: boolean;
  created_at: string;
};

type ObservabilitySummary = {
  request_rate_per_s: number;
  error_rate: number;
  p95_latency_ms: number;
  cache_hit_rate: number;
  rate_limited_per_s: number;
  tokens_total: number;
  cost_total: number;
  scope: string;
  tenant?: string | null;
};

const MODEL_PRESETS = ["tinyllama:latest", "llama3.1:8b", "mock-1"] as const;
type ModelPreset = (typeof MODEL_PRESETS)[number];

const isPresetModel = (value: string) =>
  MODEL_PRESETS.includes(value as ModelPreset);

const defaultHeaders: HeaderMeta = {
  requestId: null,
  modelChosen: null,
  provider: null,
  routeReason: null,
  cache: null,
  retryAfter: null,
  tokensRemaining: null,
  spendRemaining: null
};

const tabs = ["Chat", "Limits", "Observability", "Grafana", "Keys"] as const;

type Tab = (typeof tabs)[number];

function estimateTokens(text: string): number {
  const normalized = text.trim();
  if (!normalized) {
    return 0;
  }
  return Math.max(1, Math.ceil(normalized.length / 4));
}

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
  const [activeTab, setActiveTab] = useState<Tab>("Chat");
  const [apiKey, setApiKey] = useLocalStorage("llm_gateway_api_key", "");
  const [storedKeysRaw, setStoredKeysRaw] = useLocalStorage(
    "llm_gateway_api_keys",
    "[]"
  );
  const [selectedKeyName, setSelectedKeyName] = useState("");
  const [adminKey, setAdminKey] = useLocalStorage("llm_gateway_admin_key", "");
  const [lastGeneratedKey, setLastGeneratedKey] = useLocalStorage(
    "llm_gateway_last_api_key",
    ""
  );
  const [model, setModel] = useLocalStorage("llm_gateway_model", "mock-1");
  const [modelPreset, setModelPreset] = useState<ModelPreset | "custom">(
    isPresetModel(model) ? model : "custom"
  );
  const [customModel, setCustomModel] = useState(
    isPresetModel(model) ? "" : model
  );
  const [temperature, setTemperature] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [stream] = useState(true);
  const [responseText, setResponseText] = useState("");
  const [status, setStatus] = useState<"idle" | "working" | "done">("idle");
  const [error, setError] = useState<ErrorDetail | null>(null);
  const [headers, setHeaders] = useState<HeaderMeta>(defaultHeaders);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [gatewayHealthy, setGatewayHealthy] = useState(false);
  const [apiKeysReady, setApiKeysReady] = useState(false);
  const [adminKeyInvalid, setAdminKeyInvalid] = useState(false);
  const startupAtRef = useRef<number>(Date.now());
  const [usageMeta, setUsageMeta] = useState<UsageMeta>({
    promptTokens: null,
    completionTokens: null,
    totalTokens: null,
    costUsd: null
  });

  const baseUrl = useMemo(() => {
    return import.meta.env.VITE_GATEWAY_URL || "http://localhost:8000";
  }, []);

  const resetMeta = () => {
    setHeaders(defaultHeaders);
    setLatencyMs(null);
    setUsageMeta({
      promptTokens: null,
      completionTokens: null,
      totalTokens: null,
      costUsd: null
    });
  };

  const updateHeaders = (res: Response) => {
    setHeaders({
      requestId: res.headers.get("X-Request-Id"),
      modelChosen: res.headers.get("X-Model-Chosen"),
      provider: res.headers.get("X-Provider"),
      routeReason: res.headers.get("X-Route-Reason"),
      cache: res.headers.get("X-Cache"),
      retryAfter: res.headers.get("Retry-After"),
      tokensRemaining: res.headers.get("X-RateLimit-Tokens-Remaining"),
      spendRemaining: res.headers.get("X-RateLimit-Spend-Remaining")
    });
  };

  const sendChat = async () => {
    if (!apiKey) {
      setError({ code: "missing_api_key", message: "Set an API key in Settings." });
      return;
    }
    if (!userPrompt.trim()) {
      setError({ code: "missing_prompt", message: "Enter a user message." });
      return;
    }
    setStatus("working");
    setError(null);
    setResponseText("");
    resetMeta();

    const payload: Record<string, unknown> = {
      model,
      messages: [
        ...(systemPrompt.trim()
          ? [{ role: "system", content: systemPrompt.trim() }]
          : []),
        { role: "user", content: userPrompt.trim() }
      ],
      stream
    };

    if (temperature.trim()) {
      payload.temperature = Number(temperature);
    }
    if (maxTokens.trim()) {
      payload.max_tokens = Number(maxTokens);
    }

    const startedAt = performance.now();

    try {
      if (stream) {
        await sendStream(payload, startedAt);
      } else {
        await sendJson(payload, startedAt);
      }
      setStatus("done");
    } catch (err) {
      setStatus("idle");
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Request failed. Ensure the gateway is running on http://localhost:8000 and refresh the page.";
      const friendly =
        message === "Failed to fetch"
          ? "Gateway not reachable. Start the stack with `docker compose up --build`, then refresh."
          : message;
      setError({ code: "client_error", message: friendly });
    }
  };

  const sendJson = async (payload: Record<string, unknown>, startedAt: number) => {
    const res = await fetch(`${baseUrl}/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify(payload)
    });

    updateHeaders(res);

    if (!res.ok) {
      const err = await readError(res);
      setError(err);
      setStatus("idle");
      return;
    }

    const data = (await res.json()) as { content: string; model: string };
    const content = data.content ?? "";
    setResponseText(content);

    const promptTokens = estimateTokens(
      `${systemPrompt.trim()} ${userPrompt.trim()}`
    );
    const completionTokens = estimateTokens(content);
    const totalTokens = promptTokens + completionTokens;

    setUsageMeta({
      promptTokens,
      completionTokens,
      totalTokens,
      costUsd: null
    });

    setLatencyMs(Math.round(performance.now() - startedAt));
  };

  const sendStream = async (payload: Record<string, unknown>, startedAt: number) => {
    const res = await fetch(`${baseUrl}/v1/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify(payload)
    });

    updateHeaders(res);

    if (!res.ok || !res.body) {
      const err = await readError(res);
      setError(err);
      setStatus("idle");
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundaryIndex = buffer.indexOf("\n\n");
      while (boundaryIndex >= 0) {
        const chunk = buffer.slice(0, boundaryIndex);
        buffer = buffer.slice(boundaryIndex + 2);
        handleSseChunk(chunk, startedAt);
        boundaryIndex = buffer.indexOf("\n\n");
      }
    }
  };

  const handleSseChunk = (chunk: string, startedAt: number) => {
    const lines = chunk
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.startsWith("data:"));

    if (!lines.length) {
      return;
    }

    const data = lines
      .map((line) => line.replace(/^data:\s?/, ""))
      .join("\n")
      .trim();

    if (!data) {
      return;
    }

    if (data === "[DONE]") {
      setLatencyMs(Math.round(performance.now() - startedAt));
      return;
    }

    let payload: StreamPayload | null = null;
    try {
      payload = JSON.parse(data) as StreamPayload;
    } catch {
      return;
    }

    if (payload.error) {
      setError(payload.error);
      setStatus("idle");
      return;
    }

    if (payload.content) {
      setResponseText((prev) => prev + payload.content);
    }

    if (payload.done && payload.usage) {
      const totalTokens = payload.usage.total_tokens ?? 0;
      setUsageMeta({
        promptTokens: payload.usage.prompt_tokens,
        completionTokens: payload.usage.completion_tokens,
        totalTokens,
        costUsd: null
      });
    }
  };

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

  const [limitsTenant, setLimitsTenant] = useState("");
  const [tokenLimit, setTokenLimit] = useState("");
  const [spendLimit, setSpendLimit] = useState("");
  const [adminMessage, setAdminMessage] = useState<string | null>(null);
  const [obsSummary, setObsSummary] = useState<ObservabilitySummary | null>(null);
  const [obsLoading, setObsLoading] = useState(false);
  const [bootstrapKey, setBootstrapKey] = useState<string | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [rotateError, setRotateError] = useState<string | null>(null);
  const [apiKeyName, setApiKeyName] = useState("");
  const [apiKeys, setApiKeys] = useState<ApiKeyEntry[]>([]);
  const [apiKeysError, setApiKeysError] = useState<string | null>(null);
  const [apiKeysLoading, setApiKeysLoading] = useState(false);
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

  const adminConfigured = Boolean(adminKey.trim());
  const storedKeys: { name: string; key: string }[] = useMemo(() => {
    try {
      const parsed = JSON.parse(storedKeysRaw) as { name: string; key: string }[];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }, [storedKeysRaw]);
  const activeKeyNames = useMemo(() => {
    return new Set(
      apiKeys.filter((key) => key.active).map((key) => key.name ?? key.tenant)
    );
  }, [apiKeys]);
  const activeStoredKeys = useMemo(() => {
    return storedKeys.filter((entry) => activeKeyNames.has(entry.name));
  }, [storedKeys, activeKeyNames]);
  const retrievableKeyNames = useMemo(() => {
    return new Set(storedKeys.map((entry) => entry.name));
  }, [storedKeys]);
  const activeKeyOptions = useMemo(() => {
    return apiKeys
      .filter((key) => key.active)
      .map((key) => ({
        name: key.name ?? key.tenant,
        tenant: key.tenant,
        retrievable: retrievableKeyNames.has(key.name ?? key.tenant)
      }));
  }, [apiKeys, retrievableKeyNames]);

  const callAdmin = async <T,>(path: string, body?: Record<string, unknown>) => {
    if (!adminKey) {
      setAdminMessage("Set an admin API key in Settings.");
      return null;
    }
    setAdminMessage(null);
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
      setAdminMessage(`${err.code}: ${err.message}`);
      return null;
    }

    return (await res.json()) as T;
  };

  const updateLimits = async () => {
    const payload = await callAdmin<unknown>("/v1/admin/limits", {
      tenant: limitsTenant.trim(),
      token_limit_per_day: tokenLimit ? Number(tokenLimit) : null,
      spend_limit_per_day_usd: spendLimit ? Number(spendLimit) : null
    });
    if (payload) {
      setAdminMessage("Limits updated.");
    }
  };

  const fetchObservability = async () => {
    if (!apiKey) {
      setApiKeysError("Select an API key first.");
      return;
    }
    setObsLoading(true);
    try {
      const res = await fetch(`${baseUrl}/v1/observability/summary`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${apiKey}`
        }
      });
      if (!res.ok) {
        const err = await readError(res);
        setApiKeysError(`${err.code}: ${err.message}`);
        setObsLoading(false);
        return;
      }
      const data = (await res.json()) as ObservabilitySummary;
      setObsSummary(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setApiKeysError(message);
    } finally {
      setObsLoading(false);
    }
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
      const now = Date.now();
      const inStartupWindow = now - startupAtRef.current < 20000;
      if (inStartupWindow) {
        return;
      }
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
      setAdminMessage("Admin key generated and stored.");
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
      setAdminMessage("Admin key rotated and stored.");
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
                  setAdminKeyInvalid(false);
                  return await refreshApiKeys(data.api_key, true);
                }
            } catch {
              // fall through to show invalid key message
            }
          }
          setAdminKey("");
          setApiKeys([]);
          setAdminKeyInvalid(true);
          setApiKeysError("Admin key is invalid. Generate a new admin key.");
        }
        setApiKeysLoading(false);
        return false;
      }
      const data = (await res.json()) as { keys: ApiKeyEntry[] };
      setApiKeys(data.keys);
      setApiKeysError(null);
      setApiKeysReady(true);
      setAdminKeyInvalid(false);
      return true;
    } catch (err) {
      const now = Date.now();
      const inStartupWindow = now - startupAtRef.current < 20000;
      if (inStartupWindow) {
        setApiKeysReady(false);
        return false;
      }
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
      setApiKey(payload.api_key);
      setLastGeneratedKey(payload.api_key);
      const next = [
        ...storedKeys.filter((entry) => entry.name !== payload.tenant),
        { name: payload.tenant, key: payload.api_key }
      ];
      setStoredKeysRaw(JSON.stringify(next));
      setSelectedKeyName(payload.tenant);
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

  const handlePresetChange = (next: string) => {
    if (next === "custom") {
      setModelPreset("custom");
      setModel(customModel);
      return;
    }
    if (isPresetModel(next)) {
      setModelPreset(next);
      setModel(next);
    }
  };

  const handleCustomModelChange = (value: string) => {
    setCustomModel(value);
    if (modelPreset === "custom") {
      setModel(value);
    }
  };

  const topErrors = [
    error ? `${error.code}: ${error.message}` : null,
    bootstrapError,
    rotateError,
    apiKeysError,
    pricingError
  ].filter(Boolean) as string[];


  useEffect(() => {
    if (adminKey) {
      setApiKeysReady(false);
      setAdminKeyInvalid(false);
      refreshApiKeys(undefined, true);
      loadPricing();
    } else {
      setApiKeys([]);
      setApiKeysError(null);
      setApiKeysReady(true);
      setAdminKeyInvalid(false);
    }
  }, [adminKey]);

  useEffect(() => {
    if (!adminKey) {
      return;
    }
    if (adminKeyInvalid) {
      return;
    }
    let cancelled = false;
    let inFlight = false;
    let attempts = 0;
    const maxAttempts = 20;
    const poll = async () => {
      if (cancelled || inFlight) {
        return;
      }
      inFlight = true;
      const ok = await refreshApiKeys(undefined, true);
      inFlight = false;
      attempts += 1;
      if (ok && apiKeys.length > 1) {
        cancelled = true;
        return;
      }
      if (attempts >= maxAttempts) {
        cancelled = true;
      }
    };
    const timer = window.setInterval(poll, 1500);
    poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [adminKey, adminKeyInvalid, apiKeys.length]);

  useEffect(() => {
    const existing = pricingMap[model];
    if (existing) {
      setPricingForm({ ...existing });
    } else {
      setPricingForm({ input: 0, output: 0, cached: 0 });
    }
    setPricingSaved(false);
  }, [model, pricingMap]);

  useEffect(() => {
    if (!selectedKeyName) {
      return;
    }
    const stored = activeStoredKeys.find((entry) => entry.name === selectedKeyName);
    if (stored) {
      setApiKey(stored.key);
      return;
    }
    setApiKey("");
    setApiKeysError(
      `Key "${selectedKeyName}" not available in this browser. Generate a new key.`
    );
  }, [selectedKeyName, activeStoredKeys]);

  useEffect(() => {
    let cancelled = false;
    const checkHealth = async () => {
      try {
        const res = await fetch(`${baseUrl}/health`, { method: "GET" });
        if (!cancelled) {
          setGatewayHealthy(res.ok);
        }
        if (res.ok) {
          cancelled = true;
        }
      } catch {
        if (!cancelled) {
          setGatewayHealthy(false);
        }
      }
    };
    const timer = window.setInterval(checkHealth, 1500);
    checkHealth();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [baseUrl]);

  useEffect(() => {
    const reloadCountKey = "llm_gateway_autoreload_count";
    const maxReloads = 4;
    const rawCount = window.sessionStorage.getItem(reloadCountKey);
    const reloadCount = rawCount ? Number(rawCount) : 0;
    if (reloadCount >= maxReloads) {
      return;
    }
    let cancelled = false;
    const checkAndReload = async () => {
      try {
        const res = await fetch(`${baseUrl}/health`, { method: "GET" });
        if (!res.ok) {
          return;
        }
        if (!adminKey || apiKeys.length > 1) {
          cancelled = true;
          return;
        }
        if (cancelled) {
          return;
        }
        window.sessionStorage.setItem(reloadCountKey, String(reloadCount + 1));
        window.location.reload();
        cancelled = true;
      } catch {
        // ignore and retry on next interval
      }
    };

    checkAndReload();
    return () => {
      cancelled = true;
    };
  }, [baseUrl, adminKey, apiKeys.length]);

  const appReady = gatewayHealthy && (!adminKey || apiKeysReady || adminKeyInvalid);
  const loadingMessage = gatewayHealthy
    ? "Fetching keys..."
    : "Starting gateway services...";

  if (!appReady) {
    return (
      <div className="loading-screen">
        <div className="loading-card">
          <div className="loading-title">LLM Gateway</div>
          <div className="loading-subtitle">{loadingMessage}</div>
          <div className="loading-spinner" />
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span>Developer Portal</span>
          <h1>LLM Gateway</h1>
        </div>
        <nav className="nav">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={tab === activeTab ? "active" : undefined}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </nav>
        <div style={{ marginTop: 24, display: "grid", gap: 8 }}>
          <div className="pill">Gateway: {baseUrl}</div>
          <a className="pill" href="http://localhost:3000" target="_blank" rel="noreferrer">
            Grafana dashboards
          </a>
        </div>
      </aside>
      <main className="main">
        <div className="header">
          <h2>{activeTab}</h2>
          <div className="pill">Status: {status}</div>
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

        {activeTab === "Chat" && (
          <div className="grid">
            <div className="card">
              <h3>Chat Request</h3>
              <div className="form">
                <div className="row">
                  <div className="field">
                    <label>Model Preset</label>
                    <select
                      value={modelPreset}
                      onChange={(e) => handlePresetChange(e.target.value)}
                    >
                      {MODEL_PRESETS.map((preset) => (
                        <option key={preset} value={preset}>
                          {preset}
                        </option>
                      ))}
                      <option value="custom">Custom</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>Temperature</label>
                    <input
                      value={temperature}
                      onChange={(e) => setTemperature(e.target.value)}
                      placeholder="0.2"
                    />
                  </div>
                  <div className="field">
                    <label>Max Tokens</label>
                    <input
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(e.target.value)}
                      placeholder="256"
                    />
                  </div>
                  <div className="field">
                    <label>API Key</label>
                    <select
                      value={selectedKeyName}
                      onChange={(e) => setSelectedKeyName(e.target.value)}
                    >
                      <option value="">Select a key</option>
                      {activeKeyOptions.map((entry) => (
                        <option key={entry.name} value={entry.name}>
                          {entry.name}
                          {entry.retrievable ? "" : " (requires key)"}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                {modelPreset === "custom" && (
                  <div className="field">
                    <label>Custom Model</label>
                    <input
                      value={customModel}
                      onChange={(e) => handleCustomModelChange(e.target.value)}
                      placeholder="tinyllama:latest"
                    />
                  </div>
                )}
                <div className="field">
                  <label>System</label>
                  <textarea
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    placeholder="Optional system instructions."
                  />
                </div>
                <div className="field">
                  <label>User</label>
                  <textarea
                    value={userPrompt}
                    onChange={(e) => setUserPrompt(e.target.value)}
                    placeholder="Ask the model something."
                  />
                </div>
                <div className="row">
                  <button className="button" onClick={sendChat} disabled={status === "working"}>
                    Send to /v1/chat
                  </button>
                  <button
                    className="button secondary"
                    onClick={() => {
                      setResponseText("");
                      setError(null);
                      resetMeta();
                    }}
                  >
                    Clear
                  </button>
                </div>
              </div>
            </div>

            <div className="card">
              <h3>Response</h3>
              {!error && responseText && (
                <div className="banner success">Response received.</div>
              )}
              {!error && !responseText && (
                <div className="banner warning">No response yet.</div>
              )}
              <div className="field" style={{ marginTop: 12 }}>
                <label>Output</label>
                <textarea value={responseText} readOnly />
              </div>
            </div>

            <div className="card">
              <h3>Metadata</h3>
              <div className="meta-grid">
                <div>
                  <div className="pill">Request ID</div>
                  <div className="value">{headers.requestId ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Model Chosen</div>
                  <div className="value">{headers.modelChosen ?? model}</div>
                </div>
                <div>
                  <div className="pill">Provider</div>
                  <div className="value">{headers.provider ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Route Reason</div>
                  <div className="value">{headers.routeReason ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Cache</div>
                  <div className="value">{headers.cache ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Latency (ms)</div>
                  <div className="value">{latencyMs ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Prompt Tokens</div>
                  <div className="value">{usageMeta.promptTokens ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Completion Tokens</div>
                  <div className="value">{usageMeta.completionTokens ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Total Tokens</div>
                  <div className="value">{usageMeta.totalTokens ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Cost (USD)</div>
                  <div className="value">
                    {usageMeta.costUsd !== null ? usageMeta.costUsd.toFixed(6) : "-"}
                  </div>
                </div>
                <div>
                  <div className="pill">Tokens Remaining</div>
                  <div className="value">{headers.tokensRemaining ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Spend Remaining</div>
                  <div className="value">{headers.spendRemaining ?? "-"}</div>
                </div>
                <div>
                  <div className="pill">Retry-After</div>
                  <div className="value">{headers.retryAfter ?? "-"}</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "Limits" && (
          <div className="grid">
            <div className="card">
              <h3>Tenant Limits</h3>
              <div className="form">
                <div className="field">
                  <label>Tenant</label>
                  <select
                    value={limitsTenant}
                    onChange={(e) => setLimitsTenant(e.target.value)}
                  >
                    <option value="">Select an active key</option>
                    {apiKeys
                      .filter((key) => key.active)
                      .map((key) => (
                        <option key={key.id} value={key.tenant}>
                          {key.name ?? key.tenant}
                        </option>
                      ))}
                  </select>
                </div>
                <div className="row">
                  <div className="field">
                    <label>Token Limit / Day</label>
                    <input value={tokenLimit} onChange={(e) => setTokenLimit(e.target.value)} />
                  </div>
                  <div className="field">
                    <label>Spend Limit / Day (USD)</label>
                    <input value={spendLimit} onChange={(e) => setSpendLimit(e.target.value)} />
                  </div>
                </div>
                <button className="button" onClick={updateLimits}>
                  Save Limits
                </button>
              </div>
              {adminMessage && <div className="banner warning">{adminMessage}</div>}
            </div>
          </div>
        )}

        {activeTab === "Observability" && (
          <div className="grid">
            <div className="card">
              <h3>Observability</h3>
              <div className="form">
                <button className="button" onClick={fetchObservability}>
                  Refresh Metrics
                </button>
              </div>
              {obsLoading && <div className="value">Loading metrics...</div>}
              {!obsLoading && obsSummary && (
                <div className="meta-grid" style={{ marginTop: 12 }}>
                  <div>
                    <div className="pill">Requests / sec</div>
                    <div className="value">{obsSummary.request_rate_per_s.toFixed(2)}</div>
                  </div>
                  <div>
                    <div className="pill">Error Rate</div>
                    <div className="value">{(obsSummary.error_rate * 100).toFixed(2)}%</div>
                  </div>
                  <div>
                    <div className="pill">P95 Latency (ms)</div>
                    <div className="value">{obsSummary.p95_latency_ms.toFixed(0)}</div>
                  </div>
                  <div>
                    <div className="pill">Cache Hit Rate</div>
                    <div className="value">{(obsSummary.cache_hit_rate * 100).toFixed(2)}%</div>
                  </div>
                  <div>
                    <div className="pill">Rate Limited / sec</div>
                    <div className="value">{obsSummary.rate_limited_per_s.toFixed(2)}</div>
                  </div>
                  <div>
                    <div className="pill">Tokens Total</div>
                    <div className="value">{obsSummary.tokens_total.toFixed(0)}</div>
                  </div>
                  <div>
                    <div className="pill">Cost Total (USD)</div>
                    <div className="value">{obsSummary.cost_total.toFixed(6)}</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === "Keys" && (
          <div className="grid">
            <div className="card">
              <h3>Credentials</h3>
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
        )}

        {activeTab === "Grafana" && (
          <div className="grid">
            <div className="card">
              <h3>Grafana</h3>
              <div className="field">
                <label>Dashboard</label>
                <div className="value">LLM Gateway (embedded)</div>
              </div>
              <div style={{ marginTop: 12, borderRadius: 16, overflow: "hidden" }}>
                <iframe
                  title="Grafana"
                  src="http://localhost:3000/d/llm-gateway/llm-gateway?orgId=1&refresh=5s&kiosk"
                  style={{ width: "100%", height: "70vh", border: "none" }}
                />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
