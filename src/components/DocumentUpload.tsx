"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, Link2, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { backendApi, type LlmProvider } from "@/lib/api/backend";
import { dispatchIngestComplete, dispatchIngestRoute, dispatchIngestStart } from "@/lib/ingestRouteEvents";
import { useI18n } from "@/lib/i18n/I18nProvider";

interface DocumentUploadProps {
  onIngestComplete?: () => void;
  disabled?: boolean;
}

/** Poll until backend reports completed or failed — no client-side timeout. */
const POLL_INTERVAL_MS = 2000;

export function DocumentUpload({ onIngestComplete, disabled }: DocumentUploadProps) {
  const { t } = useI18n();
  const [url, setUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [llmProvider, setLlmProvider] = useState<LlmProvider>("local");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    backendApi
      .getLlmConfig()
      .then((cfg) => setLlmProvider(cfg.provider))
      .catch(() => {});
  }, []);

  const pollTask = useCallback(
    async (taskId: string) => {
      const started = Date.now();

      for (;;) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        const task = await backendApi.ingestStatus(taskId);
        const elapsedMin = Math.floor((Date.now() - started) / 60_000);
        if (task.ingest_llm_provider) {
          dispatchIngestRoute({
            provider: task.ingest_llm_provider,
            model: task.ingest_llm_model ?? undefined,
          });
          setLlmProvider(task.ingest_llm_provider);
        }
        const pct =
          typeof task.progress === "number" && task.progress > 0
            ? ` (${Math.round(task.progress * 100)}%)`
            : "";
        const base = task.message || task.status;
        setStatus(
          elapsedMin > 0
            ? `${base}${pct} — ${t("upload.stillProcessing", { min: String(elapsedMin) })}`
            : `${base}${pct}`
        );
        if (task.status === "completed") {
          setUploading(false);
          dispatchIngestComplete();
          const action = task.result?.action as string | undefined;
          const deduped = task.result?.deduplicated === true;
          if (deduped || action === "skip") {
            setStatus(task.message || "Already indexed — duplicate skipped");
          } else if (action === "replace") {
            setStatus(task.message || "Updated — replaced previous version");
          } else {
            setStatus(task.message || "Document ingested into Neo4j + Qdrant");
          }
          onIngestComplete?.();
          return;
        }
        if (task.status === "failed") {
          dispatchIngestComplete();
          throw new Error(task.error ?? t("upload.ingestFailed"));
        }
      }
    },
    [onIngestComplete, t]
  );

  const handleFile = async (file: File) => {
    setUploading(true);
    dispatchIngestStart();
    setError(null);
    setStatus(t("upload.uploading"));
    try {
      const task = await backendApi.ingestFile(file);
      setStatus(task.message);
      await pollTask(task.task_id);
    } catch (e) {
      dispatchIngestComplete();
      setError(e instanceof Error ? e.message : t("upload.uploadFailed"));
      setUploading(false);
    }
  };

  const handleUrl = async () => {
    if (!url.trim()) return;
    setUploading(true);
    dispatchIngestStart();
    setError(null);
    setStatus(t("upload.fetchingUrl"));
    try {
      const task = await backendApi.ingestUrl(url.trim());
      await pollTask(task.task_id);
      setUrl("");
    } catch (e) {
      dispatchIngestComplete();
      setError(e instanceof Error ? e.message : t("upload.urlFailed"));
      setUploading(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
      <p className="text-sm font-medium text-slate-300">{t("upload.title")}</p>
      <p className="mt-1 text-xs text-slate-500">{t("upload.subtitle")}</p>
      <p className="mt-1 text-xs text-slate-600">{t("upload.paywallHint")}</p>
      <p className="mt-1 text-xs text-slate-600">{t("upload.hybridRoutingHint")}</p>
      <p className="mt-1 text-xs text-slate-600">
        {llmProvider === "yandex" ? t("upload.longPdfHintYandex") : t("upload.longPdfHintLocal")}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.doc"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
        <button
          type="button"
          disabled={disabled || uploading}
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-2 rounded-lg bg-cyan-600/20 px-3 py-2 text-xs text-cyan-300 hover:bg-cyan-600/30 disabled:opacity-50"
        >
          {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          {t("upload.uploadButton")}
        </button>
      </div>

      <div className="mt-2 flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t("upload.urlPlaceholder")}
          disabled={disabled || uploading}
          className="flex-1 rounded-lg border border-slate-700 bg-slate-950/50 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600"
        />
        <button
          type="button"
          disabled={disabled || uploading || !url.trim()}
          onClick={handleUrl}
          className="flex items-center gap-1 rounded-lg border border-slate-600 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          <Link2 className="h-3.5 w-3.5" />
          {t("upload.urlButton")}
        </button>
      </div>

      {status && !error && (
        <p className="mt-2 flex items-center gap-1 text-xs text-emerald-400">
          {uploading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3 w-3" />
          )}
          {status}
        </p>
      )}
      {error && (
        <p className="mt-2 flex items-center gap-1 text-xs text-red-400">
          <AlertCircle className="h-3 w-3" />
          {error}
        </p>
      )}
    </div>
  );
}
