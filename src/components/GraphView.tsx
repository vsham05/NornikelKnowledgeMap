"use client";

import { useEffect, useRef, useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { getEntityLabel, graphCollisionRadius, graphNodeRadius, minNodeCenterDistance } from "@/lib/graph";
import { prepareDocumentHubGraph } from "@/lib/graphLayout";
import { relationLabel } from "@/lib/adapters/backend";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { EntityType } from "@/lib/types";

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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as any;

async function loadForceCollide() {
  const mod = await import("d3-force-3d");
  return mod.forceCollide;
}

interface GraphViewProps {
  nodes: GraphNode[];
  links: GraphEdge[];
  onNodeClick?: (node: GraphNode) => void;
  highlightId?: string;
  emptyMessage?: string;
  typeFilter?: EntityType | null;
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
};

function useContainerSize(ref: React.RefObject<HTMLDivElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) {
        setSize({ width: Math.floor(width), height: Math.floor(height) });
      }
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);

  return size;
}

export function GraphView({
  nodes,
  links,
  onNodeClick,
  highlightId,
  emptyMessage,
  typeFilter,
}: GraphViewProps) {
  const { t, locale } = useI18n();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const initialFitDone = useRef(false);
  const { width, height } = useContainerSize(containerRef);
  const ready = width > 0 && height > 0;

  const hubLayout = useMemo(
    () => prepareDocumentHubGraph(nodes, links),
    [nodes, links]
  );

  const visibleIds = useMemo(() => {
    const layoutNodes = hubLayout.nodes;
    const layoutLinks = hubLayout.links;
    if (!typeFilter) return null;
    const ids = new Set<string>();
    for (const n of layoutNodes) {
      if (n.type === typeFilter) ids.add(n.id);
    }
    for (const link of layoutLinks) {
      const src = typeof link.source === "string" ? link.source : String(link.source);
      const tgt = typeof link.target === "string" ? link.target : String(link.target);
      if (ids.has(src)) ids.add(tgt);
      if (ids.has(tgt)) ids.add(src);
    }
    return ids;
  }, [hubLayout.nodes, hubLayout.links, typeFilter]);

  const presentLegendTypes = useMemo(() => {
    const types = new Set(hubLayout.nodes.map((n) => n.type));
    return LEGEND_TYPES.filter((t) => types.has(t));
  }, [hubLayout.nodes]);

  const graphData = useMemo(
    () => ({
      nodes: hubLayout.nodes.map((n) => ({
        ...n,
        color:
          visibleIds && !visibleIds.has(n.id) ? "rgba(100, 116, 139, 0.2)" : n.color,
      })),
      links: hubLayout.links
        .filter((l) => {
          if (!visibleIds) return true;
          const src = typeof l.source === "string" ? l.source : String(l.source);
          const tgt = typeof l.target === "string" ? l.target : String(l.target);
          return visibleIds.has(src) && visibleIds.has(tgt);
        })
        .map((l) => ({
          source: l.source,
          target: l.target,
          relation: l.relation,
        })),
    }),
    [hubLayout, visibleIds]
  );

  const fitGraph = useCallback(() => {
    if (!fgRef.current) return;
    fgRef.current.zoomToFit(400, 28);
    const z = fgRef.current.zoom() ?? 1;
    if (z < 0.55) {
      fgRef.current.zoom(0.58, 0);
    }
  }, []);

  const zoomBy = useCallback((factor: number) => {
    if (!fgRef.current) return;
    const current = fgRef.current.zoom() ?? 1;
    const next = Math.min(8, Math.max(0.15, current * factor));
    fgRef.current.zoom(next, 300);
  }, []);

  useEffect(() => {
    initialFitDone.current = false;
  }, [nodes, links, typeFilter]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    let cancelled = false;
    void loadForceCollide().then((forceCollide) => {
      if (cancelled || !fgRef.current) return;
      const g = fgRef.current;

      g.d3Force("charge")?.strength(-25);
      g.d3Force(
        "collision",
        forceCollide<GraphNode & { val?: number }>()
          .radius((n: GraphNode & { val?: number }) => graphCollisionRadius(n.val ?? 4))
          .strength(1)
          .iterations(3)
      );
      g.d3Force("link")
        ?.distance((link: { source: GraphNode | string; target: GraphNode | string }) => {
          const srcType = typeof link.source === "object" ? link.source?.type : undefined;
          const tgtType = typeof link.target === "object" ? link.target?.type : undefined;
          const types = new Set([srcType, tgtType]);
          if (types.has("material") && types.has("process")) {
            return minNodeCenterDistance(7);
          }
          if (types.has("expert") || types.has("team")) {
            return minNodeCenterDistance(5);
          }
          if (types.has("material") && types.has("article")) {
            return minNodeCenterDistance(7) + minNodeCenterDistance(9) * 0.5;
          }
          if (types.has("article")) return minNodeCenterDistance(7) * 1.4;
          if (types.has("experiment")) return minNodeCenterDistance(8);
          return minNodeCenterDistance(7);
        })
        .strength((link: { source: GraphNode | string; target: GraphNode | string }) => {
          const srcType = typeof link.source === "object" ? link.source?.type : undefined;
          const tgtType = typeof link.target === "object" ? link.target?.type : undefined;
          const types = new Set([srcType, tgtType]);
          if (types.has("material") && types.has("process")) return 0.85;
          if (types.has("expert") || types.has("team")) return 0.5;
          if (types.has("article")) return 0.35;
          return 0.4;
        });
      g.d3Force("center")?.strength(0.002);
      g.d3VelocityDecay(0.55);
    });

    return () => {
      cancelled = true;
    };
  }, [ready, nodes.length, graphData.nodes.length]);

  const handleEngineStop = useCallback(() => {
    if (initialFitDone.current) return;
    fitGraph();
    initialFitDone.current = true;
  }, [fitGraph]);

  useEffect(() => {
    if (!ready || nodes.length === 0) return;
    const t = setTimeout(() => {
      if (!initialFitDone.current) fitGraph();
    }, 150);
    return () => clearTimeout(t);
  }, [ready, nodes, links, typeFilter, width, height, fitGraph]);

  const nodeRadius = useCallback((n: GraphNode) => graphNodeRadius(n.val ?? 4), []);

  const paintPointerArea = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any, color: string, ctx: CanvasRenderingContext2D) => {
      const n = node as GraphNode & { x?: number; y?: number };
      const r = nodeRadius(n);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(n.x ?? 0, n.y ?? 0, r + 8, 0, 2 * Math.PI);
      ctx.fill();
    },
    [nodeRadius]
  );

  const paintNode = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = node as GraphNode & { x?: number; y?: number };
      const label = truncateLabel(displayName(n, t("graph.unknown")));
      const fontSize = Math.min(13, Math.max(5, 10 / Math.sqrt(globalScale)));
      const r = nodeRadius(n);
      const isHighlight = highlightId === n.id;

      ctx.beginPath();
      ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI);
      ctx.fillStyle = n.color;
      ctx.globalAlpha = isHighlight ? 1 : 0.88;
      ctx.fill();
      if (isHighlight) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2.5 / globalScale;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      if (globalScale > 0.1) {
        ctx.font = `${fontSize}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle =
          globalScale < 0.45
            ? "rgba(226, 232, 240, 0.78)"
            : "rgba(226, 232, 240, 0.92)";
        ctx.fillText(label, n.x ?? 0, (n.y ?? 0) + r + 2 / globalScale);
      }
    },
    [highlightId, nodeRadius, t]
  );

  if (nodes.length === 0) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center rounded-xl border border-slate-700/50 bg-gradient-to-b from-slate-950/80 to-slate-900/40 p-8 text-center text-slate-500">
        {emptyMessage ?? t("graph.emptyDefault")}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[420px] flex-col overflow-hidden rounded-xl border border-slate-700/60 bg-gradient-to-b from-slate-950/90 to-slate-900/50 shadow-inner shadow-black/20">
      <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 px-3 py-2">
        <div className="min-w-0 text-xs text-slate-500">
          <span className="font-medium text-slate-400">{t("graph.view")}</span>
          <span className="mx-2 text-slate-700">·</span>
          <span className="tabular-nums">
            {t("graph.nodesLinks", {
              nodes: graphData.nodes.length,
              links: graphData.links.length,
            })}
            {hubLayout.hiddenOrphans > 0 && (
              <span className="text-slate-600">
                {t("graph.hiddenOrphans", { count: hubLayout.hiddenOrphans })}
              </span>
            )}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
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

      <div ref={containerRef} className="relative min-h-0 flex-1">
        {ready && (
          <ForceGraph2D
            ref={fgRef}
            width={width}
            height={height}
            graphData={graphData}
            nodeLabel={(n: GraphNode) => {
              const name = displayName(n, t("graph.unknown"));
              return `<div style="padding:6px 10px;background:#1e293b;border-radius:6px;font-size:12px">
            <strong>${name}</strong><br/>
            <span style="color:#94a3b8">${getEntityLabel(n.type, locale)}</span>
          </div>`;
            }}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={paintPointerArea}
            linkColor={(l: { source: GraphNode | string; target: GraphNode | string }) => {
              const src = typeof l.source === "object" ? l.source : null;
              const tgt = typeof l.target === "object" ? l.target : null;
              const types = new Set([src?.type, tgt?.type]);
              if (types.has("material")) return "rgba(244, 114, 182, 0.55)";
              return "rgba(100, 116, 139, 0.45)";
            }}
            linkWidth={(l: { source: GraphNode | string; target: GraphNode | string }) => {
              const src = typeof l.source === "object" ? l.source : null;
              const tgt = typeof l.target === "object" ? l.target : null;
              return src?.type === "material" || tgt?.type === "material" ? 1.8 : 1.1;
            }}
            linkLabel={(l: { relation?: GraphEdge["relation"] }) =>
              l.relation ? relationLabel(l.relation, locale) : ""
            }
            linkDirectionalParticles={1}
            linkDirectionalParticleWidth={2}
            linkDirectionalParticleColor={() => "rgba(34, 211, 238, 0.55)"}
            onNodeClick={(n: GraphNode) => onNodeClick?.(n)}
            onEngineStop={handleEngineStop}
            onNodeDragEnd={(node: GraphNode & { x?: number; y?: number; fx?: number; fy?: number }) => {
              node.fx = node.x;
              node.fy = node.y;
            }}
            backgroundColor="rgba(2, 6, 23, 0)"
            cooldownTicks={80}
            warmupTicks={20}
            minZoom={0.25}
            maxZoom={10}
            enableNodeDrag
          />
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

        {typeFilter && (
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
