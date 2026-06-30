"use client";

import { useState, useRef, useCallback } from "react";
import { Upload, Link2, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { backendApi } from "@/lib/api/backend";

interface DocumentUploadProps {
  onIngestComplete?: () => void;
  disabled?: boolean;
}

export function DocumentUpload({ onIngestComplete, disabled }: DocumentUploadProps) {
  const [url, setUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const pollTask = useCallback(
    async (taskId: string) => {
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const task = await backendApi.ingestStatus(taskId);
        setStatus(task.message || task.status);
        if (task.status === "completed") {
          setUploading(false);
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
          throw new Error(task.error ?? "Ingestion failed");
        }
      }
      throw new Error("Ingestion timed out");
    },
    [onIngestComplete]
  );

  const handleFile = async (file: File) => {
    setUploading(true);
    setError(null);
    setStatus("Uploading…");
    try {
      const task = await backendApi.ingestFile(file);
      setStatus(task.message);
      await pollTask(task.task_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setUploading(false);
    }
  };

  const handleUrl = async () => {
    if (!url.trim()) return;
    setUploading(true);
    setError(null);
    setStatus("Fetching URL…");
    try {
      const task = await backendApi.ingestUrl(url.trim());
      await pollTask(task.task_id);
      setUrl("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "URL ingest failed");
      setUploading(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
      <p className="text-sm font-medium text-slate-300">Ingest documents</p>
      <p className="mt-1 text-xs text-slate-500">
        PDF/DOCX → MinIO · text → Qdrant · entities → Neo4j
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
          Upload PDF/DOCX
        </button>
      </div>

      <div className="mt-2 flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
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
          URL
        </button>
      </div>

      {status && !error && (
        <p className="mt-2 flex items-center gap-1 text-xs text-emerald-400">
          <CheckCircle2 className="h-3 w-3" />
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
