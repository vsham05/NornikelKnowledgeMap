"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { backendApi } from "@/lib/api/backend";
import { getEntityColor, getEntityLabel } from "@/lib/graph";
import { neo4jLabelToEntityType } from "@/lib/graphHierarchy";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { EntityType, GraphNode } from "@/lib/types";
import { SearchableEntityList, type SearchableListItem } from "@/components/SearchableEntityList";

const PAGE_SIZE = 100;
const SEARCH_DEBOUNCE_MS = 300;

interface EntityBrowsePanelProps {
  entityType: EntityType;
  onClose: () => void;
  onSelectNode: (node: GraphNode) => void;
}

export function EntityBrowsePanel({
  entityType,
  onClose,
  onSelectNode,
}: EntityBrowsePanelProps) {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<SearchableListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const offsetRef = useRef(0);
  const fetchGenRef = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(searchQuery), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  const loadPage = useCallback(
    async (reset: boolean) => {
      const gen = ++fetchGenRef.current;
      if (reset) {
        setLoading(true);
        offsetRef.current = 0;
      } else {
        setLoadingMore(true);
      }
      try {
        const page = await backendApi.browseEntities(
          entityType,
          debouncedQuery || undefined,
          PAGE_SIZE,
          reset ? 0 : offsetRef.current
        );
        if (gen !== fetchGenRef.current) return;

        const mapped: SearchableListItem[] = (page.items ?? []).map((row) => ({
          id: row.id,
          name: row.label || row.id,
          type: neo4jLabelToEntityType(row.type),
        }));

        setTotal(page.total ?? 0);
        setHasMore(Boolean(page.has_more));
        offsetRef.current = reset ? mapped.length : offsetRef.current + mapped.length;
        setItems((prev) => (reset ? mapped : [...prev, ...mapped]));
      } catch {
        if (gen === fetchGenRef.current && reset) {
          setItems([]);
          setTotal(0);
          setHasMore(false);
        }
      } finally {
        if (gen === fetchGenRef.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [entityType, debouncedQuery]
  );

  useEffect(() => {
    void loadPage(true);
  }, [loadPage]);

  const handleSelect = (id: string) => {
    const item = items.find((row) => row.id === id);
    if (!item) return;
    onSelectNode({
      id: item.id,
      name: item.name,
      type: item.type ?? entityType,
      val: 1,
      color: getEntityColor(item.type ?? entityType),
    });
  };

  return (
    <div className="flex h-full min-h-[320px] flex-col rounded-xl border border-slate-700/60 bg-slate-900/90 backdrop-blur lg:min-h-[200px]">
      <div className="flex items-center justify-between gap-2 border-b border-slate-700/60 p-4">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white"
            style={{ backgroundColor: getEntityColor(entityType) }}
          >
            {getEntityLabel(entityType, locale)}
          </span>
          <h3 className="truncate text-sm font-semibold text-slate-100">
            {t("entityBrowse.title", { label: getEntityLabel(entityType, locale) })}
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          aria-label={t("entityBrowse.close")}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {t("entityPanel.groupMembers", { count: total })}
        </div>
        <SearchableEntityList
          items={items}
          total={total}
          loading={loading}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          clientFilter={false}
          onItemClick={handleSelect}
          footer={
            hasMore ? (
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => void loadPage(false)}
                className="mt-2 w-full rounded-lg border border-slate-600/70 bg-slate-800/50 px-3 py-2 text-xs text-slate-300 transition hover:bg-slate-800 disabled:opacity-50"
              >
                {loadingMore ? t("entityBrowse.loadingMore") : t("entityBrowse.loadMore")}
              </button>
            ) : null
          }
        />
      </div>
    </div>
  );
}
