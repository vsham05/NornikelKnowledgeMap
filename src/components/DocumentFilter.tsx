"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronDown, FileText, Loader2, Trash2, X } from "lucide-react";
import { useI18n } from "@/lib/i18n/I18nProvider";

export interface DocumentOption {
  id: string;
  title: string;
}

interface DocumentFilterProps {
  documents: DocumentOption[];
  value: string;
  onChange: (documentId: string) => void;
  onDelete?: (documentId: string) => Promise<void>;
  disabled?: boolean;
  loading?: boolean;
}

function matchesQuery(title: string, id: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = `${title} ${id}`.toLowerCase();
  return q.split(/\s+/).every((token) => haystack.includes(token));
}

export function DocumentFilter({
  documents,
  value,
  onChange,
  onDelete,
  disabled,
  loading,
}: DocumentFilterProps) {
  const { t } = useI18n();
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const selected = documents.find((d) => d.id === value);
  const selectedLabel = selected?.title || (value ? value.slice(0, 8) : "");
  const allLabel = t("documentFilter.all");

  const triggerLabel = value ? selectedLabel : allLabel;
  const triggerHint = value
    ? undefined
    : t("documentFilter.allCount", { count: documents.length });

  const filtered = useMemo(() => {
    return documents.filter((doc) =>
      matchesQuery(doc.title || "", doc.id, query)
    );
  }, [documents, query]);

  const options = useMemo(() => {
    const allOption = { id: "", title: allLabel };
    if (!query.trim()) return [allOption, ...documents];
    const hits = filtered;
    if (hits.length === 0) return [];
    return hits;
  }, [allLabel, documents, filtered, query]);

  const openPanel = useCallback(() => {
    if (disabled || loading || deleting) return;
    setOpen(true);
  }, [deleting, disabled, loading]);

  const closePanel = useCallback(() => {
    setOpen(false);
    setQuery("");
    setHighlightIndex(0);
  }, []);

  const selectDocument = useCallback(
    (docId: string) => {
      onChange(docId);
      closePanel();
      triggerRef.current?.focus();
    },
    [closePanel, onChange]
  );

  const handleDeleteConfirmed = async () => {
    if (!value || !onDelete || deleting) return;
    setDeleting(true);
    try {
      await onDelete(value);
      onChange("");
      setConfirmOpen(false);
    } finally {
      setDeleting(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) closePanel();
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [closePanel, open]);

  useEffect(() => {
    setHighlightIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (open) {
      const id = window.requestAnimationFrame(() => searchRef.current?.focus());
      return () => window.cancelAnimationFrame(id);
    }
  }, [open]);

  const onSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((i) => Math.min(i + 1, Math.max(0, options.length - 1)));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (options.length > 0) {
        const pick = options[highlightIndex] ?? options[0];
        selectDocument(pick.id);
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      closePanel();
      triggerRef.current?.focus();
    }
  };

  const onTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openPanel();
    }
  };

  const busy = disabled || loading || deleting;
  const canDelete = Boolean(value && onDelete && !busy);

  return (
    <>
      <div ref={rootRef} className="flex w-full items-center gap-2">
        <FileText className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />

        <div className="relative min-w-0 flex-1 sm:max-w-md">
          <button
            ref={triggerRef}
            type="button"
            role="combobox"
            aria-expanded={open}
            aria-controls={listboxId}
            aria-label={t("documentFilter.aria")}
            title={triggerHint ? `${triggerLabel} · ${triggerHint}` : triggerLabel}
            disabled={busy}
            onClick={() => (open ? closePanel() : openPanel())}
            onKeyDown={onTriggerKeyDown}
            className="flex w-full items-center gap-2 rounded-lg border border-slate-700/80 bg-slate-900/80 py-1.5 pl-2.5 pr-2 text-left text-sm text-slate-200 transition-colors hover:border-slate-600 focus:border-cyan-500/60 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="min-w-0 flex-1 truncate">{triggerLabel}</span>
            {!value && documents.length > 0 && (
              <span className="hidden shrink-0 rounded-md bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400 sm:inline">
                {documents.length}
              </span>
            )}
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
              aria-hidden
            />
          </button>

          {open && !busy && (
            <div className="absolute left-0 right-0 z-50 mt-1 min-w-[min(100%,18rem)] overflow-hidden rounded-lg border border-slate-700/80 bg-slate-900 shadow-xl sm:min-w-[20rem]">
              <div className="border-b border-slate-800/80 p-2">
                <input
                  ref={searchRef}
                  type="search"
                  role="searchbox"
                  aria-controls={listboxId}
                  value={query}
                  placeholder={t("documentFilter.searchPlaceholder")}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={onSearchKeyDown}
                  className="w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 py-1.5 text-sm text-slate-200 placeholder:text-slate-500 focus:border-cyan-500/60 focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
                />
              </div>

              <ul
                id={listboxId}
                role="listbox"
                className="max-h-56 overflow-y-auto py-1"
              >
                {options.length === 0 ? (
                  <li className="px-3 py-2 text-xs text-slate-500">
                    {t("documentFilter.noMatches")}
                  </li>
                ) : (
                  options.map((doc, idx) => {
                    const isAll = doc.id === "";
                    const label = doc.title || doc.id.slice(0, 8);
                    const active = idx === highlightIndex;
                    const isSelected = doc.id === value;
                    return (
                      <li
                        key={doc.id || "__all__"}
                        role="option"
                        aria-selected={isSelected}
                        title={label}
                        className={`cursor-pointer px-3 py-2 ${
                          active
                            ? "bg-cyan-500/15 text-cyan-100"
                            : isSelected
                              ? "bg-slate-800/60 text-cyan-300"
                              : "text-slate-200 hover:bg-slate-800"
                        }`}
                        onMouseEnter={() => setHighlightIndex(idx)}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => selectDocument(doc.id)}
                      >
                        {isAll ? (
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{label}</div>
                            <div className="mt-0.5 text-xs text-slate-500">
                              {t("documentFilter.allHint")}
                              {documents.length > 0 && (
                                <span className="text-slate-600">
                                  {" · "}
                                  {t("documentFilter.allCount", { count: documents.length })}
                                </span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <div className="truncate text-sm">{label}</div>
                        )}
                      </li>
                    );
                  })
                )}
              </ul>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          disabled={!canDelete}
          title={t("documentFilter.deleteTitle")}
          aria-label={t("documentFilter.deleteTitle")}
          className="flex shrink-0 items-center gap-1 rounded-lg border border-red-500/40 bg-red-950/30 px-2 py-1.5 text-xs text-red-300 hover:bg-red-900/40 disabled:cursor-not-allowed disabled:border-slate-700/50 disabled:bg-slate-900/50 disabled:text-slate-600"
        >
          {deleting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Trash2 className="h-3.5 w-3.5" />
          )}
          <span className="hidden sm:inline">{t("documentFilter.delete")}</span>
        </button>
      </div>

      {confirmOpen && value && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-doc-title"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !deleting) setConfirmOpen(false);
          }}
        >
          <div className="w-full max-w-sm rounded-xl border border-slate-700/80 bg-slate-900 p-5 shadow-2xl">
            <div className="mb-3 flex items-start justify-between gap-3">
              <h2 id="delete-doc-title" className="text-base font-medium text-slate-100">
                {t("documentFilter.confirmDeleteTitle")}
              </h2>
              <button
                type="button"
                disabled={deleting}
                onClick={() => setConfirmOpen(false)}
                className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-300 disabled:opacity-50"
                aria-label={t("documentFilter.confirmDeleteCancel")}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mb-5 text-sm leading-relaxed text-slate-400">
              {t("documentFilter.deleteConfirm", { title: selectedLabel })}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                disabled={deleting}
                onClick={() => setConfirmOpen(false)}
                className="rounded-lg border border-slate-600/80 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                {t("documentFilter.confirmDeleteCancel")}
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => void handleDeleteConfirmed()}
                className="flex items-center gap-1.5 rounded-lg border border-red-500/50 bg-red-950/50 px-3 py-1.5 text-sm text-red-200 hover:bg-red-900/60 disabled:opacity-50"
              >
                {deleting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {t("documentFilter.confirmDeleteAction")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
