"use client";

import { useCallback, useEffect, useState } from "react";
import { Cpu } from "lucide-react";
import { backendApi, checkBackendHealth, type LlmProvider } from "@/lib/api/backend";
import {
  INGEST_COMPLETE_EVENT,
  INGEST_ROUTE_EVENT,
  type IngestRouteDetail,
} from "@/lib/ingestRouteEvents";
import { useI18n } from "@/lib/i18n/I18nProvider";

const OPTIONS: LlmProvider[] = ["local", "yandex"];

export function ModelSwitcher() {
  const { t } = useI18n();
  const [provider, setProvider] = useState<LlmProvider>("local");
  const [hybridOverride, setHybridOverride] = useState<LlmProvider | null>(null);
  const [yandexModel, setYandexModel] = useState("");
  const [yandexModels, setYandexModels] = useState<{ id: string; label: string; moderation_risk: boolean }[]>([]);
  const [yandexReady, setYandexReady] = useState(false);
  const [moderationRisk, setModerationRisk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const displayProvider = hybridOverride ?? provider;

  const refresh = useCallback(async () => {
    const online = await checkBackendHealth();
    if (!online) {
      setYandexReady(false);
      setYandexModels([]);
      setError(t("model.backendOffline"));
      return;
    }
    try {
      const cfg = await backendApi.getLlmConfig();
      setProvider(cfg.provider);
      setYandexReady(cfg.yandex_ready);
      setYandexModel(cfg.yandex_model);
      setYandexModels(cfg.yandex_models ?? []);
      setModerationRisk(Boolean(cfg.yandex_moderation_risk));
      if (!cfg.yandex_ready && cfg.provider === "yandex") {
        setError(t("model.yandexNotConfigured"));
      } else {
        setError(null);
      }
    } catch {
      setYandexReady(false);
      setError(t("model.unavailable"));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onRoute = (event: Event) => {
      const detail = (event as CustomEvent<IngestRouteDetail>).detail;
      if (!detail?.provider) return;
      setHybridOverride(detail.provider);
      if (detail.model && detail.provider === "yandex") {
        setYandexModel(detail.model);
      }
    };
    const onComplete = () => setHybridOverride(null);
    window.addEventListener(INGEST_ROUTE_EVENT, onRoute);
    window.addEventListener(INGEST_COMPLETE_EVENT, onComplete);
    return () => {
      window.removeEventListener(INGEST_ROUTE_EVENT, onRoute);
      window.removeEventListener(INGEST_COMPLETE_EVENT, onComplete);
    };
  }, []);

  const onProviderChange = async (value: string) => {
    const next = value as LlmProvider;
    if (next === provider) return;
    setHybridOverride(null);
    setBusy(true);
    setError(null);
    try {
      const cfg = await backendApi.setLlmProvider(next);
      setProvider(cfg.provider);
      setYandexReady(cfg.yandex_ready);
      setYandexModel(cfg.yandex_model);
      setYandexModels(cfg.yandex_models ?? []);
      setModerationRisk(Boolean(cfg.yandex_moderation_risk));
      if (typeof window !== "undefined") {
        localStorage.setItem("llm_provider", cfg.provider);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("model.switchFailed"));
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const onYandexModelChange = async (value: string) => {
    if (!value || value === yandexModel) return;
    setBusy(true);
    setError(null);
    try {
      const cfg = await backendApi.setYandexModel(value);
      setYandexModel(cfg.yandex_model);
      setModerationRisk(Boolean(cfg.yandex_moderation_risk));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("model.switchFailed"));
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const selectLabel =
    hybridOverride === "yandex"
      ? t("model.hybridYandex")
      : hybridOverride === "local"
        ? t("model.hybridLocal")
        : t(`model.${displayProvider}`);

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Cpu className="h-3.5 w-3.5 text-slate-500" aria-hidden />
        <label htmlFor="model-select" className="sr-only">
          {t("model.label")}
        </label>
        <select
          id="model-select"
          value={displayProvider}
          disabled={busy || hybridOverride !== null}
          onChange={(e) => void onProviderChange(e.target.value)}
          className={`max-w-[12rem] rounded-lg border px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 disabled:opacity-60 ${
            hybridOverride === "yandex"
              ? "border-violet-500/50 bg-violet-950/40 text-violet-200 focus:border-violet-500/60 focus:ring-violet-500/20"
              : "border-slate-700/80 bg-slate-900/80 text-slate-200 focus:border-cyan-500/60 focus:ring-cyan-500/20"
          }`}
          aria-label={t("model.label")}
          title={selectLabel}
        >
          {OPTIONS.map((code) => (
            <option key={code} value={code} disabled={code === "yandex" && !yandexReady}>
              {hybridOverride === code
                ? code === "yandex"
                  ? t("model.hybridYandex")
                  : t("model.hybridLocal")
                : t(`model.${code}`)}
            </option>
          ))}
        </select>

        {(displayProvider === "yandex" || hybridOverride === "yandex") &&
          yandexReady &&
          yandexModels.length > 0 && (
          <select
            id="yandex-model-select"
            value={yandexModel}
            disabled={busy || hybridOverride !== null}
            onChange={(e) => void onYandexModelChange(e.target.value)}
            className="max-w-[13rem] rounded-lg border border-violet-500/40 bg-violet-950/30 px-2.5 py-1.5 text-xs text-violet-100 focus:border-violet-500/60 focus:outline-none focus:ring-2 focus:ring-violet-500/20 disabled:opacity-50"
            aria-label={t("model.yandexModel")}
          >
            {yandexModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        )}
      </div>
      {hybridOverride && (
        <span className="max-w-[18rem] text-right text-[10px] text-violet-300/90">
          {hybridOverride === "yandex" ? t("model.hybridYandex") : t("model.hybridLocal")}
        </span>
      )}
      {displayProvider === "yandex" && moderationRisk && !hybridOverride && (
        <span className="max-w-[18rem] text-right text-[10px] text-amber-400/90">
          {t("model.moderationWarning")}
        </span>
      )}
      {error && (
        <span className="max-w-[18rem] text-right text-[10px] text-amber-400/90">{error}</span>
      )}
    </div>
  );
}
