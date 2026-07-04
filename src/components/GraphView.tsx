"use client";

import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type RefObject,
  type SetStateAction,
} from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import type { ForceGraphMethods } from "react-force-graph-2d";
import type { ComponentType } from "react";
import type { GraphEdge, GraphNode, EntityType } from "@/lib/types";
import {
  getEntityLabel,
  graphNodeRadius,
  getEntityColor,
  LAYOUT_ENTITY_VAL,
} from "@/lib/graph";
import {
  prepareForceGraphLayout,
  filterGraphByDocumentExpansion,
  layoutQueryFocusNodes,
  centerLayoutOnNode,
} from "@/lib/graphLayout";
import { filterNodesForLayout } from "@/lib/graphLayoutInput";
import type { GraphSearchFocus } from "@/lib/graphSearchFocus";
import { isTypeClusterNode, parseTypeClusterId } from "@/lib/graphHierarchy";
import { useI18n } from "@/lib/i18n/I18nProvider";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
}) as ComponentType<Record<string, unknown>>;

const ENTITY_NODE_VAL = LAYOUT_ENTITY_VAL;
const RING_NODE_VAL = 2;
const HUB_NODE_VAL = 14;
const OVERLAY_TOP_PAD = 44;

type LayoutNode = GraphNode & {
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
  clusterId?: string;
  clusterType?: EntityType;
  clusterSize?: number;
  layoutRole?: "ring" | "grid" | "hub";
  isCollapsedHub?: boolean;
  collapsedChildCount?: number;
  isTypeCluster?: boolean;
  typeClusterCount?: number;
  isSearchFocus?: boolean;
  isPrimaryFocus?: boolean;
  color?: string;
  val?: number;
};

type SimNode = LayoutNode & { id: string };
type SimLink = {
  source: string | SimNode;
  target: string | SimNode;
  relation?: string;
};

interface GraphViewProps {
  nodes: GraphNode[];
  links: GraphEdge[];
  className?: string;
  containerRef?: RefObject<HTMLDivElement | null>;
  onNodeClick?: (node: GraphNode) => void;
  onDocumentExpand?: (documentId: string) => void | Promise<void>;
  onTypeClusterExpand?: (documentId: string, entityType: EntityType) => void | Promise<void>;
  onDocumentCollapse?: (documentId: string) => void;
  highlightId?: string;
  emptyMessage?: string;
  typeFilter?: EntityType | null;
  selectedDocumentId?: string;
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

function nodeVisualVal(node: LayoutNode): number {
  if (node.type === "article") return HUB_NODE_VAL;
  if (node.layoutRole === "ring") return RING_NODE_VAL;
  return ENTITY_NODE_VAL;
}

type GridClusterVisual = {
  id: string;
  cx: number;
  cy: number;
  type: EntityType;
  count: number;
  color: string;
  halfW: number;
  halfH: number;
};

function collectGridClusters(nodes: LayoutNode[]): GridClusterVisual[] {
  const buckets = new Map<
    string,
    { type: EntityType; xs: number[]; ys: number[]; color: string }
  >();

  for (const node of nodes) {
    if (node.layoutRole !== "grid" || !node.clusterId || !node.clusterType) continue;
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    let bucket = buckets.get(node.clusterId);
    if (!bucket) {
      bucket = {
        type: node.clusterType,
        xs: [],
        ys: [],
        color: getEntityColor(node.clusterType),
      };
      buckets.set(node.clusterId, bucket);
    }
    bucket.xs.push(x);
    bucket.ys.push(y);
  }

  const out: GridClusterVisual[] = [];
  for (const [id, bucket] of buckets) {
    const minX = Math.min(...bucket.xs);
    const maxX = Math.max(...bucket.xs);
    const minY = Math.min(...bucket.ys);
    const maxY = Math.max(...bucket.ys);
    out.push({
      id,
      cx: (minX + maxX) / 2,
      cy: (minY + maxY) / 2,
      type: bucket.type,
      count: bucket.xs.length,
      color: bucket.color,
      halfW: (maxX - minX) / 2 + 28,
      halfH: (maxY - minY) / 2 + 28,
    });
  }
  return out;
}

function useGraphBoxSize() {
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  const attachBoxRef = useCallback((el: HTMLDivElement | null) => {
    setContainerEl(el);
  }, []);

  useLayoutEffect(() => {
    if (!containerEl) {
      setSize({ width: 0, height: 0 });
      return;
    }

    const update = () => {
      const width = Math.round(containerEl.clientWidth);
      const height = Math.round(containerEl.clientHeight);
      if (width > 0 && height > 0) {
        setSize((prev) =>
          prev.width === width && prev.height === height ? prev : { width, height }
        );
      }
    };

    update();
    requestAnimationFrame(update);
    const ro = new ResizeObserver(update);
    ro.observe(containerEl);
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [containerEl]);

  return { width: size.width, height: size.height, attachBoxRef };
}

export function GraphView({
  nodes,
  links,
  className,
  containerRef,
  onNodeClick,
  onDocumentExpand,
  onTypeClusterExpand,
  onDocumentCollapse,
  highlightId,
  emptyMessage,
  typeFilter,
  selectedDocumentId,
  expandingDocId,
  expandedDocIds,
  onExpandedDocIdsChange,
  expandedTypeKeys,
  onExpandedTypeKeysChange,
  searchFocus,
  onDismissSearchFocus,
}: GraphViewProps) {
  const { t, locale } = useI18n();
  const lastArticleClickRef = useRef<{ id: string; at: number } | null>(null);
  const fgRef = useRef<ForceGraphMethods<SimNode, SimLink> | undefined>(undefined);
  const { width: graphWidth, height: graphHeight, attachBoxRef } = useGraphBoxSize();

  const layoutInput = useMemo(() => {
    let filtered = filterNodesForLayout(nodes, links, expandedDocIds, expandedTypeKeys);
    if (selectedDocumentId && expandedDocIds.size === 0) {
      filtered = {
        nodes: filtered.nodes.filter(
          (n) => n.type !== "article" || n.id === selectedDocumentId
        ),
        links: [],
      };
    }
    return filtered;
  }, [nodes, links, expandedDocIds, expandedTypeKeys, selectedDocumentId]);

  const hubLayout = useMemo(
    () => prepareForceGraphLayout(layoutInput.nodes, layoutInput.links),
    [layoutInput.nodes, layoutInput.links]
  );

  const documentFocusedLayout = useMemo(() => {
    if (!selectedDocumentId) return hubLayout;
    if (!hubLayout.nodes.some((n) => n.id === selectedDocumentId)) return hubLayout;
    return {
      ...hubLayout,
      nodes: centerLayoutOnNode(hubLayout.nodes, selectedDocumentId),
    };
  }, [hubLayout, selectedDocumentId]);

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

  useEffect(() => {
    if (!searchFocus?.visibleIds.length || !onTypeClusterExpand) return;
    const seen = new Set<string>();
    for (const id of searchFocus.visibleIds) {
      const node = nodes.find((n) => n.id === id);
      if (!node || node.type === "article" || isTypeClusterNode(node)) continue;
      const hub = node.hubId ?? node.documentId;
      if (!hub) continue;
      const key = `${hub}:${node.type}`;
      if (seen.has(key)) continue;
      seen.add(key);
      void onTypeClusterExpand(hub, node.type);
      onExpandedTypeKeysChange((prev) => {
        if (prev.has(key)) return prev;
        const next = new Set(prev);
        next.add(key);
        return next;
      });
    }
  }, [searchFocus?.visibleIds, nodes, onTypeClusterExpand, onExpandedTypeKeysChange]);

  const expansionLayout = useMemo(() => {
    const layout = filterGraphByDocumentExpansion(documentFocusedLayout, expandedDocIds);
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
  }, [documentFocusedLayout, expandedDocIds, nodes, links]);

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
    const layoutLinks = expansionLayout.links.filter((link) => {
      const src = String(link.source);
      const tgt = String(link.target);
      return visibleIds.has(src) && visibleIds.has(tgt);
    });
    const chainLinks = (searchFocus?.chainLinks ?? []).filter((link) => {
      const src = String(link.source);
      const tgt = String(link.target);
      return visibleIds.has(src) && visibleIds.has(tgt);
    });
    const linkKeys = new Set(
      layoutLinks.map((l) => {
        const a = String(l.source);
        const b = String(l.target);
        return a < b ? `${a}|${b}` : `${b}|${a}`;
      })
    );
    const mergedLinks = [
      ...layoutLinks,
      ...chainLinks.filter((l) => {
        const a = String(l.source);
        const b = String(l.target);
        const key = a < b ? `${a}|${b}` : `${b}|${a}`;
        return !linkKeys.has(key);
      }),
    ];
    return {
      nodes: layoutQueryFocusNodes(visibleNodes, searchPrimarySet, mergedLinks),
      links: mergedLinks,
    };
  }, [expansionLayout, searchFocusSet, searchPrimarySet, searchFocus?.chainLinks]);

  const collapsedDocCount = useMemo(() => {
    const docs = documentFocusedLayout.nodes.filter((n) => n.type === "article");
    return docs.filter((d) => !expandedDocIds.has(d.id)).length;
  }, [documentFocusedLayout.nodes, expandedDocIds]);

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

  const graphNodes: LayoutNode[] = useMemo(
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
    if (!focusActive) return [];
    const visibleIdSet = new Set(focusLayout.nodes.map((n) => n.id));
    const chain = (searchFocus?.chainLinks ?? []).filter((link) => {
      const src = String(link.source);
      const tgt = String(link.target);
      return visibleIdSet.has(src) && visibleIdSet.has(tgt);
    });
    if (chain.length > 0) {
      if (!visibleIds) return chain;
      return chain.filter((l) => {
        const src = typeof l.source === "string" ? l.source : String(l.source);
        const tgt = typeof l.target === "string" ? l.target : String(l.target);
        return visibleIds.has(src) && visibleIds.has(tgt);
      });
    }
    return [];
  }, [focusActive, focusLayout.nodes, visibleIds, searchFocus?.chainLinks]);

  const focusLayoutMode = focusActive && graphNodes.length > 0;

  const graphData = useMemo(() => {
    const simNodes = graphNodes.map((node) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      return {
        ...node,
        val: nodeVisualVal(node),
        x,
        y,
        fx: x,
        fy: y,
      };
    });
    return {
      nodes: simNodes,
      links: graphLinks.map((link) => ({
        source: String(link.source),
        target: String(link.target),
        relation: link.relation,
      })),
    };
  }, [graphNodes, graphLinks]);

  const cameraScopeId = useMemo(() => {
    if (!selectedDocumentId) return undefined;
    if (graphNodes.some((n) => n.id === selectedDocumentId)) return selectedDocumentId;
    if (expandedDocIds.has(selectedDocumentId)) return selectedDocumentId;
    return undefined;
  }, [selectedDocumentId, expandedDocIds, graphNodes]);

  const fitView = useCallback(
    (scopeNodeId?: string) => {
      if (!fgRef.current || graphWidth <= 0 || graphHeight <= 0) return;

      let simNodes = graphData.nodes.filter((n) => n.x != null && n.y != null);
      if (simNodes.length === 0) return;

      const scope = scopeNodeId ?? cameraScopeId;
      if (scope) {
        const scoped = simNodes.filter(
          (n) =>
            n.id === scope ||
            n.hubId === scope ||
            n.documentId === scope
        );
        if (scoped.length > 0) simNodes = scoped;

        if (scoped.length === 1 && scoped[0].type === "article") {
          const hub = scoped[0];
          const hx = hub.x ?? 0;
          const hy = hub.y ?? 0;
          fgRef.current.centerAt(hx, hy, 400);
          fgRef.current.zoom(Math.min(1.35, 2.2), 400);
          return;
        }
      }

      const pad = 48;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const n of simNodes) {
        const r = graphNodeRadius(nodeVisualVal(n)) + 12;
        minX = Math.min(minX, n.x! - r);
        maxX = Math.max(maxX, n.x! + r);
        minY = Math.min(minY, n.y! - r);
        maxY = Math.max(maxY, n.y! + r);
      }

      const graphW = Math.max(maxX - minX, 80);
      const graphH = Math.max(maxY - minY, 80);
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const topPad = OVERLAY_TOP_PAD;
      const zoomW = (graphWidth - pad * 2) / graphW;
      const zoomH = (graphHeight - topPad - pad) / graphH;
      const zoom = Math.min(zoomW, zoomH, 2.2);

      fgRef.current.centerAt(cx, cy, 0);
      fgRef.current.zoom(Math.max(zoom, 0.35), 0);
    },
    [graphData.nodes, graphWidth, graphHeight, cameraScopeId]
  );

  const zoomBy = useCallback((factor: number) => {
    if (!fgRef.current) return;
    const current = fgRef.current.zoom();
    fgRef.current.zoom(Math.min(8, Math.max(0.12, current * factor)), 0);
  }, []);

  const nodeSignature = useMemo(
    () =>
      graphData.nodes
        .map((n) => `${n.id}@${n.x ?? 0},${n.y ?? 0}`)
        .sort()
        .join("|"),
    [graphData.nodes]
  );

  useEffect(() => {
    if (graphNodes.length === 0 || graphWidth <= 0 || graphHeight <= 0) return;
    let tries = 0;
    const attempt = () => {
      if (fgRef.current) {
        fitView();
        return;
      }
      if (tries++ < 20) window.setTimeout(attempt, 50);
    };
    const timer = window.setTimeout(attempt, 30);
    return () => window.clearTimeout(timer);
  }, [nodeSignature, graphWidth, graphHeight, cameraScopeId, fitView, graphNodes.length]);

  useEffect(() => {
    if (!selectedDocumentId || graphWidth <= 0 || graphHeight <= 0) return;
    let tries = 0;
    const attempt = () => {
      if (fgRef.current) {
        fitView(selectedDocumentId);
        return;
      }
      if (tries++ < 30) window.setTimeout(attempt, 50);
    };
    const timer = window.setTimeout(attempt, 60);
    return () => window.clearTimeout(timer);
  }, [selectedDocumentId, graphWidth, graphHeight, fitView]);

  const setFgRef = useCallback(
    (instance: ForceGraphMethods<SimNode, SimLink> | null) => {
      fgRef.current = instance ?? undefined;
      if (instance && graphNodes.length > 0 && graphWidth > 0 && graphHeight > 0) {
        requestAnimationFrame(() => fitView());
      }
    },
    [graphNodes.length, graphWidth, graphHeight, fitView]
  );

  const nameForNode = useCallback(
    (node: GraphNode) => displayName(node, t("graph.unknown")),
    [t]
  );

  const documentHubs = useMemo(
    () => graphNodes.filter((n) => n.type === "article" && !n.isCollapsedHub),
    [graphNodes]
  );
  const typeClusterNodes = useMemo(
    () => graphNodes.filter((n) => n.isTypeCluster),
    [graphNodes]
  );
  const gridClusters = useMemo(() => collectGridClusters(graphNodes), [graphNodes]);

  const paintHubSpoke = useCallback(
    (
      ctx: CanvasRenderingContext2D,
      hx: number,
      hy: number,
      tx: number,
      ty: number,
      color: string,
      globalScale: number,
      alpha: number
    ) => {
      ctx.beginPath();
      ctx.moveTo(hx, hy);
      ctx.lineTo(tx, ty);
      ctx.strokeStyle =
        color.startsWith("#") && color.length >= 7
          ? `${color}${Math.round(alpha * 255)
              .toString(16)
              .padStart(2, "0")}`
          : `rgba(148, 163, 184, ${alpha})`;
      ctx.lineWidth = Math.max(0.35, 0.55 / globalScale);
      ctx.stroke();
    },
    []
  );

  const paintBackground = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (focusLayoutMode) return;

      for (const hub of documentHubs) {
        const hubId = hub.id;
        const hx = hub.x ?? 0;
        const hy = hub.y ?? 0;

        const hubTypeClusters = typeClusterNodes.filter(
          (n) => (n.hubId ?? n.documentId) === hubId
        );
        const hubGrids = gridClusters.filter((g) => g.id.startsWith(`${hubId}:`));
        const gridTypes = new Set(
          hubGrids.map((g) => g.id.slice(hubId.length + 1))
        );

        if (hubTypeClusters.length === 0 && hubGrids.length === 0) continue;

        ctx.save();
        for (const node of hubTypeClusters) {
          if (gridTypes.has(node.type)) continue;
          paintHubSpoke(
            ctx,
            hx,
            hy,
            node.x ?? 0,
            node.y ?? 0,
            node.color || getEntityColor(node.type),
            globalScale,
            0.16
          );
        }
        for (const cluster of hubGrids) {
          paintHubSpoke(
            ctx,
            hx,
            hy,
            cluster.cx,
            cluster.cy,
            cluster.color,
            globalScale,
            0.1
          );
        }
        ctx.restore();
      }

      for (const cluster of gridClusters) {
        const x = cluster.cx - cluster.halfW;
        const y = cluster.cy - cluster.halfH;
        const w = cluster.halfW * 2;
        const h = cluster.halfH * 2;
        ctx.beginPath();
        if (typeof ctx.roundRect === "function") {
          ctx.roundRect(x, y, w, h, 6);
        } else {
          ctx.rect(x, y, w, h);
        }
        ctx.fillStyle = `${cluster.color}0a`;
        ctx.fill();
        ctx.strokeStyle = `${cluster.color}28`;
        ctx.lineWidth = Math.max(0.4, 0.9 / globalScale);
        ctx.stroke();

        if (globalScale > 0.42) {
          const title = `${getEntityLabel(cluster.type, locale)} · ${cluster.count}`;
          const fontSize = Math.max(7, 10 / globalScale);
          ctx.font = `500 ${fontSize}px system-ui, sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          ctx.fillStyle = "rgba(148, 163, 184, 0.75)";
          ctx.fillText(title, cluster.cx, cluster.cy - cluster.halfH - 4);
        }
      }
    },
    [documentHubs, typeClusterNodes, gridClusters, focusLayoutMode, locale, paintHubSpoke]
  );

  const paintNode = useCallback(
    (node: LayoutNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const r = graphNodeRadius(nodeVisualVal(node));

      if (highlightId === node.id) {
        ctx.beginPath();
        ctx.arc(x, y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      if (node.isCollapsedHub) {
        ctx.beginPath();
        ctx.arc(x, y, r + 8, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(96, 165, 250, 0.55)";
        ctx.setLineDash([4 / globalScale, 3 / globalScale]);
        ctx.lineWidth = 1.2 / globalScale;
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (node.isTypeCluster) {
        ctx.beginPath();
        ctx.arc(x, y, r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = `${node.color || "#60a5fa"}88`;
        ctx.lineWidth = Math.max(1, 2 / globalScale);
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = node.color || getEntityColor(node.type);
      ctx.globalAlpha = node.type === "article" ? 1 : 0.92;
      ctx.fill();
      ctx.globalAlpha = 1;

      const showLabel =
        focusLayoutMode ||
        node.type === "article" ||
        node.isCollapsedHub ||
        node.isTypeCluster ||
        globalScale > 0.35;
      if (showLabel) {
        const name = nameForNode(node);
        const label = node.isTypeCluster
          ? truncateLabel(`${name} (${node.typeClusterCount ?? 0})`, 24)
          : node.isCollapsedHub && (node.collapsedChildCount ?? 0) > 0
            ? truncateLabel(`${name} (+${node.collapsedChildCount})`, 28)
            : truncateLabel(name, 20);
        const fontSize = Math.max(8, Math.min(12, 11 / globalScale));
        ctx.font = `${fontSize}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.lineWidth = Math.max(2, 3 / globalScale);
        ctx.strokeStyle = "rgba(2, 6, 23, 0.85)";
        ctx.strokeText(label, x, y + r + 3);
        ctx.fillStyle = "rgba(226, 232, 240, 0.92)";
        ctx.fillText(label, x, y + r + 3);
      }
    },
    [highlightId, nameForNode, focusLayoutMode]
  );

  const paintPointerArea = useCallback(
    (node: LayoutNode, color: string, ctx: CanvasRenderingContext2D) => {
      const r = Math.max(6, graphNodeRadius(nodeVisualVal(node)) + 6);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, Math.PI * 2);
      ctx.fill();
    },
    []
  );

  const updateExpandedDocs = useCallback(
    (updater: Set<string> | ((prev: Set<string>) => Set<string>)) => {
      onExpandedDocIdsChange(updater);
    },
    [onExpandedDocIdsChange]
  );

  const handleGraphNodeClick = useCallback(
    (node: LayoutNode) => {
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
        window.setTimeout(() => fitView(parsed!.documentId), 180);
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
          window.setTimeout(() => fitView(), 80);
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
          window.setTimeout(() => fitView(node.id), 150);
        }
      }
      onNodeClick?.(node);
    },
    [
      expandedDocIds,
      fitView,
      onDocumentCollapse,
      onDocumentExpand,
      onTypeClusterExpand,
      onNodeClick,
      onExpandedTypeKeysChange,
      updateExpandedDocs,
    ]
  );

  const setRootRef = useCallback(
    (el: HTMLDivElement | null) => {
      attachBoxRef(el);
      if (containerRef) {
        (containerRef as MutableRefObject<HTMLDivElement | null>).current = el;
      }
    },
    [attachBoxRef, containerRef]
  );

  const hasGraph = nodes.length > 0;
  const graphReady = graphWidth > 0 && graphHeight > 0;

  return (
    <div
      ref={setRootRef}
      className={`relative h-[min(68vh,720px)] min-h-[420px] w-full overflow-hidden rounded-xl border border-slate-700/60 bg-[#020617] ${className ?? ""}`}
    >
      {!hasGraph && (
        <div className="flex h-full items-center justify-center p-8 text-center text-slate-500">
          {emptyMessage ?? t("graph.emptyDefault")}
        </div>
      )}

      {hasGraph && graphReady && (
        <ForceGraph2D
          ref={setFgRef}
          width={graphWidth}
          height={graphHeight}
          graphData={graphData}
          backgroundColor="#020617"
          nodeRelSize={1}
          nodeVal={(node: LayoutNode) => nodeVisualVal(node)}
          nodeLabel={(node: LayoutNode) => nameForNode(node)}
          nodeCanvasObject={paintNode}
          nodeCanvasObjectMode={() => "replace"}
          nodePointerAreaPaint={paintPointerArea}
          linkColor={() =>
            focusLayoutMode ? "rgba(56, 189, 248, 0.8)" : "rgba(51, 65, 85, 0.22)"
          }
          linkWidth={focusLayoutMode ? 2.4 : 0.35}
          linkDirectionalParticles={focusLayoutMode ? 4 : 0}
          linkDirectionalParticleWidth={focusLayoutMode ? 2.5 : 0}
          linkDirectionalParticleSpeed={focusLayoutMode ? 0.005 : 0}
          d3AlphaDecay={1}
          d3VelocityDecay={0.9}
          warmupTicks={0}
          cooldownTicks={0}
          enableNodeDrag={false}
          enableZoomInteraction
          enablePanInteraction
          onRenderFramePre={paintBackground}
          onNodeClick={(node: LayoutNode) => handleGraphNodeClick(node)}
        />
      )}

      {hasGraph && (
        <>
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/90 px-3 py-2 backdrop-blur-sm">
        <div className="pointer-events-auto min-w-0 text-xs text-slate-500">
          <span className="font-medium text-slate-400">{t("graph.view")}</span>
          <span className="mx-2 text-slate-700">·</span>
          <span className="tabular-nums">
            {t("graph.nodesLinks", {
              nodes: graphNodes.length,
              links: graphLinks.length,
            })}
            {collapsedDocCount > 0 && (
              <span className="text-slate-600">
                {t("graph.collapsedDocs", { count: collapsedDocCount })}
              </span>
            )}
          </span>
        </div>
        <div className="pointer-events-auto flex shrink-0 items-center gap-1">
          {focusLayoutMode && onDismissSearchFocus && (
            <button
              type="button"
              onClick={onDismissSearchFocus}
              className="mr-1 rounded-md border border-cyan-500/40 bg-cyan-950/50 px-2 py-1 text-[10px] font-medium text-cyan-200"
            >
              {t("graph.showFullGraph")}
            </button>
          )}
          <button type="button" onClick={() => zoomBy(1.35)} className="rounded-md border border-slate-700/80 bg-slate-900/80 p-1.5 text-slate-400" aria-label={t("graph.zoomIn")}>
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button type="button" onClick={() => zoomBy(0.74)} className="rounded-md border border-slate-700/80 bg-slate-900/80 p-1.5 text-slate-400" aria-label={t("graph.zoomOut")}>
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => fitView()}
            className="rounded-md border border-slate-700/80 bg-slate-900/80 p-1.5 text-slate-400"
            aria-label={t("graph.fitView")}
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {expandingDocId && (
        <div className="pointer-events-none absolute left-1/2 top-12 z-10 -translate-x-1/2 rounded-lg border border-cyan-500/40 bg-slate-900/95 px-3 py-1.5 text-xs text-cyan-200">
          {t("graph.loadingDocument")}
        </div>
      )}

      <div className="pointer-events-none absolute bottom-2 left-2 right-2 z-10 flex flex-wrap gap-1 rounded-lg border border-slate-800/60 bg-slate-950/80 px-2 py-1.5">
        {presentLegendTypes.map((type) => (
          <span
            key={type}
            className="rounded px-2 py-0.5 text-[10px] uppercase text-slate-400"
            style={{ borderLeft: `3px solid ${LEGEND_COLORS[type]}` }}
          >
            {getEntityLabel(type, locale)}
          </span>
        ))}
      </div>
        </>
      )}
    </div>
  );
}
