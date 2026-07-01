"use client";

import { useEffect, useRef, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { getEntityLabel } from "@/lib/graph";
import { relationLabel } from "@/lib/adapters/backend";
import type { EntityType } from "@/lib/types";

function displayName(node: GraphNode): string {
  const name = node.name?.trim();
  if (name) return name;
  const id = node.id?.trim();
  if (id) return id.length > 12 ? `${id.slice(0, 8)}…` : id;
  return "Unknown";
}

function truncateLabel(name: string, max = 22): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as any;

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
  "mode",
  "team",
  "property",
];

export function GraphView({
  nodes,
  links,
  onNodeClick,
  highlightId,
  emptyMessage,
  typeFilter,
}: GraphViewProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);

  const visibleIds = useMemo(() => {
    if (!typeFilter) return null;
    const ids = new Set<string>();
    for (const n of nodes) {
      if (n.type === typeFilter) ids.add(n.id);
    }
    for (const link of links) {
      const src = typeof link.source === "string" ? link.source : String(link.source);
      const tgt = typeof link.target === "string" ? link.target : String(link.target);
      if (ids.has(src)) ids.add(tgt);
      if (ids.has(tgt)) ids.add(src);
    }
    return ids;
  }, [nodes, links, typeFilter]);

  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({
        ...n,
        color:
          visibleIds && !visibleIds.has(n.id) ? "rgba(100, 116, 139, 0.2)" : n.color,
      })),
      links: links
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
    [nodes, links, visibleIds]
  );

  useEffect(() => {
    const t = setTimeout(() => fgRef.current?.zoomToFit(400, 60), 300);
    return () => clearTimeout(t);
  }, [nodes, links]);

  const nodeRadius = useCallback((n: GraphNode) => Math.sqrt(n.val ?? 4) * 3.5, []);

  // Required when using nodeCanvasObject — otherwise clicks do not register.
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
      const label = truncateLabel(displayName(n));
      const fontSize = Math.max(10 / globalScale, 2.5);
      const r = nodeRadius(n);
      const isHighlight = highlightId === n.id;

      ctx.beginPath();
      ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI);
      ctx.fillStyle = n.color;
      ctx.globalAlpha = isHighlight ? 1 : 0.85;
      ctx.fill();
      if (isHighlight) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      ctx.font = `${fontSize}px Sans-Serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "rgba(226, 232, 240, 0.9)";
      ctx.fillText(label, n.x ?? 0, (n.y ?? 0) + r + 1);
    },
    [highlightId, nodeRadius]
  );

  if (nodes.length === 0) {
    return (
      <div className="flex h-full min-h-[360px] items-center justify-center rounded-xl border border-slate-700/50 bg-slate-950/60 p-8 text-center text-slate-500">
        {emptyMessage ?? "No graph data to display"}
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-slate-700/50 bg-slate-950/60">
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        nodeLabel={(n: GraphNode) => {
          const name = displayName(n);
          return `<div style="padding:6px 10px;background:#1e293b;border-radius:6px;font-size:12px">
            <strong>${name}</strong><br/>
            <span style="color:#94a3b8">${getEntityLabel(n.type)}</span>
          </div>`;
        }}
        nodeCanvasObject={paintNode}
        nodePointerAreaPaint={paintPointerArea}
        linkColor={() => "rgba(100, 116, 139, 0.45)"}
        linkLabel={(l: { relation?: GraphEdge["relation"] }) =>
          l.relation ? relationLabel(l.relation) : ""
        }
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={2}
        linkDirectionalParticleColor={() => "rgba(34, 211, 238, 0.5)"}
        onNodeClick={(n: GraphNode) => onNodeClick?.(n)}
        backgroundColor="rgba(2, 6, 23, 0.4)"
        cooldownTicks={80}
      />
      <div className="absolute bottom-3 left-3 flex flex-wrap gap-2">
        {LEGEND_TYPES.map((type) => (
          <span
            key={type}
            className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wider ${
              typeFilter === type ? "text-slate-100" : "text-slate-400"
            }`}
            style={{
              borderLeft: `3px solid ${
                {
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
                }[type]
              }`,
            }}
          >
            {getEntityLabel(type)}
          </span>
        ))}
      </div>
      {typeFilter && (
        <div className="absolute right-3 top-3 rounded-lg border border-cyan-500/30 bg-slate-900/90 px-2 py-1 text-[10px] text-cyan-300">
          Showing {getEntityLabel(typeFilter)} + neighbors
        </div>
      )}
    </div>
  );
}
