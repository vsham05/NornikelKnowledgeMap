"use client";

import { useState, useCallback } from "react";
import { Search, Sparkles } from "lucide-react";

interface SearchBarProps {
  onSearch: (query: string) => void;
  loading?: boolean;
  disabled?: boolean;
}

export function SearchBar({ onSearch, loading, disabled }: SearchBarProps) {
  const [query, setQuery] = useState("");

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (query.trim() && !disabled) onSearch(query.trim());
    },
    [query, onSearch, disabled]
  );

  return (
    <form onSubmit={handleSubmit} className="relative w-full">
      <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        disabled={disabled}
        placeholder="Search your knowledge base…"
        className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 py-4 pl-12 pr-32 text-slate-100 placeholder:text-slate-500 shadow-lg shadow-black/20 backdrop-blur focus:border-cyan-500/60 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={loading || disabled || !query.trim()}
        className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
      >
        <Sparkles className="h-4 w-4" />
        {loading ? "Searching…" : "Search"}
      </button>
    </form>
  );
}
