"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { getEntityLabel } from "@/lib/graph";
import { prepareForceGraphLayout, filterGraphByDocumentExpansion, filterVisualGraphLinks } from "@/lib/graphLayout";
import { filterNodesForLayout } from "@/lib/graphLayoutInput";
import type { GraphSearchFocus } from "@/lib/graphSearchFocus";
import { isTypeClusterNode, parseTypeClusterId } from "@/lib/graphHierarchy";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { EntityType } from "@/lib/types";
import {
  ForceGraphCanvas,
  type ForceGraphCanvasHandle,
  type ForceGraphNode,
} from "@/components/ForceGraphCanvas";

function displayName(node: GraphNode, unknownLabel: string): string {
  const name = node.name?.trim();
  if (name) return name;
  const id = node.id?.trim();
  if (id) return id.length > 12 ? `${id.slice(0, 8)}…` : id;
  return unknownLabel;
}

function truncateLabel(name: string, max = 22): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

interface GraphViewProps {
  nodes: GraphNode[];
  links: GraphEdge[];
  onNodeClick?: (node: GraphNode) => void;
  onDocumentExpand?: (documentId: string) => void | Promise<void>;
  onTypeClusterExpand?: (documentId: string, entityType: EntityType) => void | Promise<void>;
  onDocumentCollapse?: (documentId: string) => void;
  highlightId?: string;
  emptyMessage?: string;
  typeFilter?: EntityType | null;
  focusNodeId?: string;
  expandingDocId?: string | null;
  expandingTypeKey?: string | null;
  expandedDocIds: Set<string>;
  onExpandedDocIdsChange: Dispatch<SetStateAction<Set<string>>>;
  expandedTypeKeys: Set<string>;
  onExpandedTypeKeysChange: Dispatch<SetStateAction<Set<string>>>;
  searchFocus?: GraphSearchFocus | null;
  onDismissSearchFocus?: () => void;
}

const LEGEND_TYPES: EntityType[] = [
  "article",
  "experiment",
  "material",
  "process",
  "equipment",
  "facility",
  "expert",
  "team",
  "figures",
  "property",
];

const LEGEND_COLORS: Record<EntityType, string> = {
  material: "#f472b6",
  experiment: "#34d399",
  mode: "#a78bfa",
  property: "#fbbf24",
  conclusion: "#2dd4bf",
  article: "#60a5fa",
  team: "#fb923c",
  setup: "#94a3b8",
  topic: "#64748b",
  equipment: "#78716c",
  process: "#38bdf8",
  facility: "#c084fc",
  expert: "#fdba74",
  figures: "#a855f7",
};

function useContainerSize(ref: React.RefObject<HTMLDivElement | null>) {
  const [size, setSize] = useState({ width: 800, height: 420 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const update = () => {
      const rect = el.getBoundingClientRect();
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      if (width > 0 && height > 0) {
        setSize({ width, height });
      }
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [ref]);

  return size;
}

export function GraphView({
  nodes,
  links,
  onNodeClick,
  onDocumentExpand,
  onTypeClusterExpand,
  onDocumentCollapse,
  highlightId,
  emptyMessage,
  typeFilter,
  focusNodeId,
  expandingDocId,
  expandingTypeKey,
  expandedDocIds,
  onExpandedDocIdsChange,
  expandedTypeKeys,
  onExpandedTypeKeysChange,
  searchFocus,
  onDismissSearchFocus,
}: GraphViewProps) {
  const { t, locale } = useI18n();
  const lastArticleClickRef = useRef<{ id: string; at: number } | null>(null);
  const canvasRef = useRef<ForceGraphCanvasHandle>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { width, height } = useContainerSize(containerRef);

  const layoutInput = useMemo(
    () => filterNodesForLayout(nodes, links, expandedDocIds, expandedTypeKeys),
    [nodes, links, expandedDocIds, expandedTypeKeys]
  );

  const hubLayout = useMemo(
    () => prepareForceGraphLayout(layoutInput.nodes, layoutInput.links),
    [layoutInput.nodes, layoutInput.links]
  );

  useEffect(() => {
    if (!searchFocus?.documentIds?.length) return;
    onExpandedDocIdsChange((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const id of searchFocus.documentIds!) {
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [searchFocus, onExpandedDocIdsChange]);

  const expansionLayout = useMemo(() => {
    const layout = filterGraphByDocumentExpansion(hubLayout, expandedDocIds);
    const entityCounts = new Map<string, number>();
    for (const node of nodes) {
      if (node.type === "article") continue;
      const hub = node.hubId ?? node.documentId;
      if (!hub) continue;
      if (node.isTypeCluster && (node.typeClusterCount ?? 0) > 0) {
        entityCounts.set(hub, (entityCounts.get(hub) ?? 0) + (node.typeClusterCount ?? 0));
      }
    }
    const docIds = new Set(nodes.filter((n) => n.type === "article").map((n) => n.id));
    if (entityCounts.size === 0) {
      for (const link of links) {
        const src = String(link.source);
        const tgt = String(link.target);
        if (docIds.has(src) && !docIds.has(tgt)) {
          entityCounts.set(src, (entityCounts.get(src) ?? 0) + 1);
        } else if (docIds.has(tgt) && !docIds.has(src)) {
          entityCounts.set(tgt, (entityCounts.get(tgt) ?? 0) + 1);
        }
      }
    }
    return {
      nodes: layout.nodes.map((node) => {
        if (node.type !== "article") return node;
        const count = entityCounts.get(node.id) ?? node.collapsedChildCount ?? 0;
        if (count <= 0 || expandedDocIds.has(node.id)) return node;
        return {
          ...node,
          val: Math.max(node.val ?? 12, 16),
          collapsedChildCount: count,
          isCollapsedHub: true,
        };
      }),
      links: layout.links,
    };
  }, [hubLayout, expandedDocIds, nodes, links]);

  const searchFocusSet = useMemo(
    () => (searchFocus?.visibleIds.length ? new Set(searchFocus.visibleIds) : null),
    [searchFocus]
  );
  const searchPrimarySet = useMemo(
    () => new Set(searchFocus?.primaryIds ?? []),
    [searchFocus?.primaryIds]
  );
  const focusActive = Boolean(searchFocusSet && searchFocusSet.size > 0);

  const focusLayout = useMemo(() => {
    if (!searchFocusSet || searchFocusSet.size === 0) {
      return expansionLayout;
    }
    const hasVisibleChild = (docId: string) =>
      expansionLayout.nodes.some(
        (n) => n.hubId === docId && n.type !== "article" && searchFocusSet.has(n.id)
      );

    const visibleNodes = expansionLayout.nodes.filter((n) => {
      if (!searchFocusSet.has(n.id)) return false;
      if (n.type === "article" && hasVisibleChild(n.id)) return false;
      return true;
    });
    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    const visibleLinks = expansionLayout.links.filter((link) => {
      const src = String(link.source);
      const tgt = String(link.target);
      return visibleIds.has(src) && visibleIds.has(tgt);
    });
    return { nodes: visibleNodes, links: visibleLinks };
  }, [expansionLayout, searchFocusSet]);

  const collapsedDocCount = useMemo(() => {
    const docs = hubLayout.nodes.filter((n) => n.type === "article");
    return docs.filter((d) => !expandedDocIds.has(d.id)).length;
  }, [hubLayout.nodes, expandedDocIds]);

  const visibleIds = useMemo(() => {
    if (!typeFilter) return null;
    const ids = new Set<string>();
    for (const n of focusLayout.nodes) {
      if (n.type === typeFilter) ids.add(n.id);
    }
    for (const link of focusLayout.links) {
      const src = typeof link.source === "string" ? link.source : String(link.source);
      const tgt = typeof link.target === "string" ? link.target : String(link.target);
      if (ids.has(src)) ids.add(tgt);
      if (ids.has(tgt)) ids.add(src);
    }
    return ids;
  }, [focusLayout.nodes, focusLayout.links, typeFilter]);

  const presentLegendTypes = useMemo(() => {
    const types = new Set(focusLayout.nodes.map((n) => n.type));
    return LEGEND_TYPES.filter((ty) => types.has(ty));
  }, [focusLayout.nodes]);

  const graphNodes: ForceGraphNode[] = useMemo(
    () =>
      focusLayout.nodes
        .filter((n) => !visibleIds || visibleIds.has(n.id))
        .map((n) => {
          const isPrimary = searchPrimarySet.has(n.id);
          const isSearchFocus = focusActive && searchFocusSet!.has(n.id);
          const dimmed = visibleIds && !visibleIds.has(n.id);
          return {
            ...n,
            val: (n.val ?? 4) * (isPrimary ? 1.15 : 1),
            color: dimmed
              ? "rgba(100, 116, 139, 0.2)"
              : isSearchFocus && !isPrimary
                ? `${n.color}99`
                : n.color,
            isSearchFocus,
            isPrimaryFocus: isPrimary,
          };
        }),
    [focusLayout.nodes, visibleIds, searchFocusSet, searchPrimarySet, focusActive]
  );

  const graphLinks = useMemo(() => {
    // Entity–entity edges are for Q&A focus mode only; default view is nodes-only grids.
    if (!focusActive) return [];

    const nodeById = new Map(focusLayout.nodes.map((n) => [n.id, n]));
    let filtered = filterVisualGraphLinks(focusLayout.links, nodeById);
    if (visibleIds) {
      filtered = filtered.filter((l) => {
        const src = typeof l.source === "string" ? l.source : String(l.source);
        const tgt = typeof l.target === "string" ? l.target : String(l.target);
        return visibleIds.has(src) && visibleIds.has(tgt);
      });
    }
    return filtered;
  }, [focusActive, focusLayout.links, focusLayout.nodes, visibleIds]);

  const clusterLabel = useCallback(
    (type: EntityType) => getEntityLabel(type, locale),
    [locale]
  );

  const fitGraph = useCallback(() => canvasRef.current?.fitView(), []);
  const zoomBy = useCallback((factor: number) => canvasRef.current?.zoomBy(factor), []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
    };
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, []);

  const updateExpandedDocs = useCallback(
    (updater: Set<string> | ((prev: Set<string>) => Set<string>)) => {
      onExpandedDocIdsChange(updater);
    },
    [onExpandedDocIdsChange]
  );

  const handleGraphNodeClick = useCallback(
    (node: ForceGraphNode) => {
      if (isTypeClusterNode(node)) {
        const parsed = parseTypeClusterId(node.id);
        if (parsed) void onTypeClusterExpand?.(parsed.documentId, parsed.entityType);
        onExpandedTypeKeysChange((prev) => {
          const key = `${parsed!.documentId}:${parsed!.entityType}`;
          if (prev.has(key)) return prev;
          const next = new Set(prev);
          next.add(key);
          return next;
        });
        onNodeClick?.(node);
        window.setTimeout(() => fitGraph(), 180);
        return;
      }

      if (node.type === "article") {
        const now = Date.now();
        const last = lastArticleClickRef.current;
        if (expandedDocIds.has(node.id) && last?.id === node.id && now - last.at < 450) {
          updateExpandedDocs((prev) => {
            const next = new Set(prev);
            next.delete(node.id);
            return next;
          });
          onDocumentCollapse?.(node.id);
          lastArticleClickRef.current = null;
          window.setTimeout(() => fitGraph(), 80);
          return;
        }
        lastArticleClickRef.current = { id: node.id, at: now };

        if (!expandedDocIds.has(node.id)) {
          void onDocumentExpand?.(node.id);
          updateExpandedDocs((prev) => {
            const next = new Set(prev);
            next.add(node.id);
            return next;
          });
          window.setTimeout(() => fitGraph(), 120);
        }
      }
      onNodeClick?.(node);
    },
    [expandedDocIds, fitGraph, onDocumentCollapse, onDocumentExpand, onTypeClusterExpand, onNodeClick, onExpandedTypeKeysChange, updateExpandedDocs]
  );

  const nameForNode = useCallback(
    (node: GraphNode) => displayName(node, t("graph.unknown")),
    [t]
  );

  if (nodes.length === 0) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center rounded-xl border border-slate-700/50 bg-gradient-to-b from-slate-950/80 to-slate-900/40 p-8 text-center text-slate-500">
        {emptyMessage ?? t("graph.emptyDefault")}
      </div>
    );
  }

  const focusLayoutMode = focusActive && graphNodes.length > 0;

  return (
    <div className="flex h-full min-h-[420px] flex-col overflow-hidden rounded-xl border border-slate-700/60 bg-gradient-to-b from-slate-950/90 to-slate-900/50 shadow-inner shadow-black/20">
      <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 px-3 py-2">
        <div className="min-w-0 text-xs text-slate-500">
          <span className="font-medium text-slate-400">{t("graph.view")}</span>
          <span className="mx-2 text-slate-700">·</span>
          <span className="tabular-nums">
            {t("graph.nodesLinks", {
              nodes: graphNodes.length,
              links: graphLinks.length,
            })}
            {hubLayout.hiddenOrphans > 0 && (
              <span className="text-slate-600">
                {t("graph.hiddenOrphans", { count: hubLayout.hiddenOrphans })}
              </span>
            )}
            {collapsedDocCount > 0 && (
              <span className="text-slate-600">
                {t("graph.collapsedDocs", { count: collapsedDocCount })}
              </span>
            )}
            {searchFocusSet && searchFocusSet.size > 0 && (
              <span className="text-cyan-500">
                {t("graph.searchFocus", { count: graphNodes.length })}
              </span>
            )}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {focusLayoutMode && onDismissSearchFocus && (
            <button
              type="button"
              onClick={onDismissSearchFocus}
              className="mr-1 rounded-md border border-cyan-500/40 bg-cyan-950/50 px-2 py-1 text-[10px] font-medium text-cyan-200 transition hover:border-cyan-400/60 hover:bg-cyan-900/50"
            >
              {t("graph.showFullGraph")}
            </button>
          )}
          <button
            type="button"
            onClick={() => zoomBy(1.35)}
            className="rounded-md border border-slate-700/80 bg-slate-900/80 p-1.5 text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
            title={t("graph.zoomIn")}
            aria-label={t("graph.zoomIn")}
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => zoomBy(0.74)}
            className="rounded-md border border-slate-700/80 bg-slate-900/80 p-1.5 text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
            title={t("graph.zoomOut")}
            aria-label={t("graph.zoomOut")}
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={fitGraph}
            className="rounded-md border border-slate-700/80 bg-slate-900/80 p-1.5 text-slate-400 transition hover:border-slate-600 hover:text-slate-200"
            title={t("graph.fitView")}
            aria-label={t("graph.fitView")}
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="relative min-h-[360px] w-full flex-1 overscroll-contain"
        style={{ overscrollBehavior: "contain", touchAction: "none" }}
      >
        <ForceGraphCanvas
          ref={canvasRef}
          nodes={graphNodes}
          links={graphLinks}
          width={width}
          height={height}
          highlightId={highlightId}
          focusNodeId={focusNodeId}
          onNodeClick={handleGraphNodeClick}
          displayName={nameForNode}
          truncateLabel={truncateLabel}
          clusterLabel={clusterLabel}
        />

        {expandingDocId && (
          <div className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-lg border border-cyan-500/40 bg-slate-900/95 px-3 py-1.5 text-xs text-cyan-200">
            {t("graph.loadingDocument")}
          </div>
        )}

        {expandingTypeKey && (
          <div className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-lg border border-violet-500/40 bg-slate-900/95 px-3 py-1.5 text-xs text-violet-200">
            {t("graph.loadingType")}
          </div>
        )}

        <div className="pointer-events-none absolute inset-0 rounded-b-xl ring-1 ring-inset ring-slate-800/40" />

        <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-wrap gap-1.5 rounded-lg border border-slate-800/60 bg-slate-950/75 px-2.5 py-2 backdrop-blur-sm">
          {presentLegendTypes.map((type) => (
            <span
              key={type}
              className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wider ${
                typeFilter === type ? "text-slate-100" : "text-slate-400"
              }`}
              style={{ borderLeft: `3px solid ${LEGEND_COLORS[type]}` }}
            >
              {getEntityLabel(type, locale)}
            </span>
          ))}
        </div>

        {searchFocusSet && searchFocusSet.size > 0 && (
          <div className="absolute right-3 top-3 rounded-lg border border-cyan-500/40 bg-slate-900/90 px-2.5 py-1 text-[10px] text-cyan-300 backdrop-blur-sm">
            {t("graph.searchFocusBadge")}
          </div>
        )}
        {typeFilter && !searchFocusSet && (
          <div className="absolute right-3 top-3 rounded-lg border border-cyan-500/30 bg-slate-900/90 px-2.5 py-1 text-[10px] text-cyan-300 backdrop-blur-sm">
            {t("graph.filterBadge", {
              type: getEntityLabel(typeFilter, locale),
            })}
          </div>
        )}
      </div>
    </div>
  );
}
