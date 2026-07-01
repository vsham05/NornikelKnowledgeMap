"use client";

import { FileText } from "lucide-react";

export interface DocumentOption {
  id: string;
  title: string;
}

interface DocumentFilterProps {
  documents: DocumentOption[];
  value: string;
  onChange: (documentId: string) => void;
  disabled?: boolean;
  loading?: boolean;
}

export function DocumentFilter({
  documents,
  value,
  onChange,
  disabled,
  loading,
}: DocumentFilterProps) {
  return (
    <div className="flex items-center gap-2">
      <FileText className="h-4 w-4 shrink-0 text-slate-500" />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || loading}
        className="min-w-0 flex-1 rounded-lg border border-slate-700/80 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 focus:border-cyan-500/60 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        aria-label="Filter by document"
      >
        <option value="">All documents (auto-select best match)</option>
        {documents.map((doc) => (
          <option key={doc.id} value={doc.id}>
            {doc.title || doc.id.slice(0, 8)}
          </option>
        ))}
      </select>
    </div>
  );
}
