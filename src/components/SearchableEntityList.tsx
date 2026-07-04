"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { getEntityColor, getEntityLabel } from "@/lib/graph";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { EntityType } from "@/lib/types";

export type SearchableListItem = {
  id: string;
  name: string;
  type?: EntityType;
  subtitle?: string;
};

interface SearchableEntityListProps {
  items: SearchableListItem[];
  total?: number;
  loading?: boolean;
  emptyLabel?: string;
  noResultsLabel?: string;
  /** Server-side search: parent handles fetch on query change */
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;
  searchPlaceholder?: string;
  /** Client-side filter when onSearchQueryChange is not set */
  clientFilter?: boolean;
  onItemClick?: (id: string) => void;
  maxHeightClass?: string;
  footer?: React.ReactNode;
}

function normalizeSearch(text: string): string {
  return text.trim().toLowerCase();
}

export function SearchableEntityList({
  items,
  total,
  loading,
  emptyLabel,
  noResultsLabel,
  searchQuery: controlledQuery,
  onSearchQueryChange,
  searchPlaceholder,
  clientFilter = true,
  onItemClick,
  maxHeightClass = "max-h-[360px]",
  footer,
}: SearchableEntityListProps) {
  const { t, locale } = useI18n();
  const [localQuery, setLocalQuery] = useState("");
  const query = controlledQuery !== undefined ? controlledQuery : localQuery;
  const setQuery = onSearchQueryChange ?? setLocalQuery;

  const filtered = useMemo(() => {
    if (!clientFilter || onSearchQueryChange) return items;
    const q = normalizeSearch(query);
    if (!q) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        (item.subtitle?.toLowerCase().includes(q) ?? false)
    );
  }, [items, query, clientFilter, onSearchQueryChange]);

  const displayItems = onSearchQueryChange ? items : filtered;
  const showCount = total ?? items.length;

  return (
    <div className="mt-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={searchPlaceholder ?? t("entityBrowse.searchPlaceholder")}
          className="w-full rounded-lg border border-slate-700/60 bg-slate-800/50 py-2 pl-8 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-cyan-500/50 focus:outline-none focus:ring-1 focus:ring-cyan-500/30"
        />
      </div>

      {loading && displayItems.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">{t("entityPanel.loadingMembers")}</p>
      ) : displayItems.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">
          {query.trim()
            ? noResultsLabel ?? t("entityBrowse.noResults")
            : emptyLabel ?? t("entityPanel.noGroupMembers")}
        </p>
      ) : (
        <ul className={`mt-2 ${maxHeightClass} space-y-1.5 overflow-y-auto pr-1`}>
          {displayItems.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onItemClick?.(item.id)}
                className="w-full rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-left transition hover:border-slate-600 hover:bg-slate-800/70"
              >
                <div className="flex min-w-0 items-center gap-2">
                  {item.type && (
                    <span
                      className="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-white"
                      style={{ backgroundColor: getEntityColor(item.type) }}
                    >
                      {getEntityLabel(item.type, locale)}
                    </span>
                  )}
                  <span className="truncate text-sm text-slate-200">{item.name}</span>
                </div>
                {item.subtitle && (
                  <div className="mt-0.5 truncate text-[10px] text-slate-500">{item.subtitle}</div>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {footer}
      {!loading && showCount > 0 && (
        <p className="mt-2 text-[10px] text-slate-500">
          {t("entityBrowse.showing", {
            shown: displayItems.length,
            total: showCount,
          })}
        </p>
      )}
    </div>
  );
}
