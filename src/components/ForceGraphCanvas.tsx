"use client";

import dynamic from "next/dynamic";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ForceGraphMethods } from "react-force-graph-2d";
import type { ComponentType } from "react";
import type { EntityType, GraphEdge, GraphNode } from "@/lib/types";
import { graphNodeRadius, getEntityColor, getEntityLabel, LAYOUT_ENTITY_VAL } from "@/lib/graph";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
}) as ComponentType<Record<string, unknown>>;

const ENTITY_NODE_VAL = LAYOUT_ENTITY_VAL;
const RING_NODE_VAL = 2;
const HUB_NODE_VAL = 14;
/** zoomToFit on 1–2 nodes treats the bbox as a point and zooms in excessively */
const SINGLE_NODE_FIT_ZOOM = 1.0;
const MAX_AUTO_FIT_ZOOM = 2.4;

export type ForceGraphNode = GraphNode & {
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
  clusterId?: string;
  clusterCx?: number;
  clusterCy?: number;
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

export interface ForceGraphCanvasHandle {
  fitView: () => void;
  centerOnNode: (nodeId: string) => boolean;
  zoomBy: (factor: number) => void;
}

interface ForceGraphCanvasProps {
  nodes: ForceGraphNode[];
  links: GraphEdge[];
  width: number;
  height: number;
  highlightId?: string;
  focusNodeId?: string;
  onNodeClick?: (node: ForceGraphNode) => void;
  displayName: (node: GraphNode) => string;
  truncateLabel: (name: string, max?: number) => string;
  clusterLabel: (type: EntityType) => string;
}

type SimNode = ForceGraphNode & { id: string };
type SimLink = {
  source: string | SimNode;
  target: string | SimNode;
  relation?: string;
};

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

function nodeVisualVal(node: ForceGraphNode): number {
  if (node.type === "article") return HUB_NODE_VAL;
  if (node.layoutRole === "ring") return RING_NODE_VAL;
  return ENTITY_NODE_VAL;
}

function collectGridClusters(nodes: ForceGraphNode[]): GridClusterVisual[] {
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

export const ForceGraphCanvas = forwardRef<ForceGraphCanvasHandle, ForceGraphCanvasProps>(
  function ForceGraphCanvas(
    {
      nodes,
      links,
      width,
      height,
      highlightId,
      focusNodeId,
      onNodeClick,
      displayName,
      truncateLabel,
      clusterLabel,
    },
    ref
  ) {
    const [canvasReady, setCanvasReady] = useState(false);
    const mountedRef = useRef(false);
    const didInitialFitRef = useRef(false);
    const fgRef = useRef<ForceGraphMethods<SimNode, SimLink> | undefined>(undefined);
    const clusterLabelRef = useRef(clusterLabel);
    clusterLabelRef.current = clusterLabel;

    const resolveClusterLabel = useCallback((type: EntityType): string => {
      const fn = clusterLabelRef.current;
      if (typeof fn === "function") return fn(type);
      return getEntityLabel(type);
    }, []);

    const dataKey = `${nodes.length}:${links.length}:${focusNodeId ?? ""}`;
    const gridClusters = useMemo(() => collectGridClusters(nodes), [nodes]);

    const hubNode = useMemo(
      () => nodes.find((n) => n.type === "article" && !n.isCollapsedHub),
      [nodes]
    );

    const typeClusterNodes = useMemo(
      () => nodes.filter((n) => n.isTypeCluster),
      [nodes]
    );

    const ringNodes = useMemo(
      () => nodes.filter((n) => n.layoutRole === "ring"),
      [nodes]
    );

    const graphData = useMemo(() => {
      const simNodes = nodes.map((node) => {
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
        links: links.map((link) => ({
          source: String(link.source),
          target: String(link.target),
          relation: link.relation,
        })),
      };
    }, [nodes, links]);

    useEffect(() => {
      mountedRef.current = true;
      setCanvasReady(true);
      return () => {
        mountedRef.current = false;
        didInitialFitRef.current = false;
      };
    }, []);

    useEffect(() => {
      didInitialFitRef.current = false;
    }, [dataKey]);

    useEffect(() => {
      if (!canvasReady || !fgRef.current) return;
      fgRef.current.d3Force("charge")?.strength(0);
      fgRef.current.d3Force("link")?.strength(0);
    }, [canvasReady, graphData]);

    const fitView = useCallback(() => {
      if (!mountedRef.current || !fgRef.current) return;
      const simNodes = graphData.nodes;
      if (simNodes.length <= 2) {
        const cx =
          simNodes.reduce((sum, n) => sum + (n.x ?? 0), 0) / Math.max(1, simNodes.length);
        const cy =
          simNodes.reduce((sum, n) => sum + (n.y ?? 0), 0) / Math.max(1, simNodes.length);
        fgRef.current.centerAt(cx, cy, 450);
        fgRef.current.zoom(SINGLE_NODE_FIT_ZOOM, 450);
        return;
      }
      fgRef.current.zoomToFit(450, 90);
      const zoom = fgRef.current.zoom();
      if (zoom > MAX_AUTO_FIT_ZOOM) {
        fgRef.current.zoom(MAX_AUTO_FIT_ZOOM, 0);
      }
    }, [graphData.nodes]);

    const centerOnNode = useCallback(
      (nodeId: string): boolean => {
        if (!mountedRef.current || !fgRef.current) return false;
        const node = graphData.nodes.find((n) => n.id === nodeId);
        if (!node || node.x == null || node.y == null) return false;
        fgRef.current.centerAt(node.x, node.y, 500);
        fgRef.current.zoom(1.35, 500);
        return true;
      },
      [graphData.nodes]
    );

    const zoomBy = useCallback((factor: number) => {
      if (!mountedRef.current || !fgRef.current) return;
      const current = fgRef.current.zoom();
      fgRef.current.zoom(Math.min(8, Math.max(0.12, current * factor)), 0);
    }, []);

    useImperativeHandle(ref, () => ({ fitView, centerOnNode, zoomBy }), [
      fitView,
      centerOnNode,
      zoomBy,
    ]);

    useEffect(() => {
      if (!canvasReady || !focusNodeId) return;
      const timer = window.setTimeout(() => {
        centerOnNode(focusNodeId);
      }, 120);
      return () => window.clearTimeout(timer);
    }, [canvasReady, focusNodeId, centerOnNode, graphData.nodes]);

    const handleEngineStop = useCallback(() => {
      if (!mountedRef.current || !fgRef.current) return;
      if (focusNodeId && centerOnNode(focusNodeId)) {
        didInitialFitRef.current = true;
        return;
      }
      if (!didInitialFitRef.current) {
        didInitialFitRef.current = true;
        fitView();
      }
    }, [focusNodeId, centerOnNode, fitView]);

    const paintBackground = useCallback(
      (ctx: CanvasRenderingContext2D, globalScale: number) => {
        if (hubNode && (ringNodes.length > 0 || typeClusterNodes.length > 0)) {
          const hx = hubNode.x ?? 0;
          const hy = hubNode.y ?? 0;
          ctx.save();
          ctx.strokeStyle = "rgba(51, 65, 85, 0.12)";
          ctx.lineWidth = Math.max(0.35, 0.6 / globalScale);
          const spokes = ringNodes.length > 0 ? ringNodes : typeClusterNodes;
          for (const node of spokes) {
            ctx.beginPath();
            ctx.moveTo(hx, hy);
            ctx.lineTo(node.x ?? 0, node.y ?? 0);
            ctx.stroke();
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
            const title = `${resolveClusterLabel(cluster.type)} · ${cluster.count}`;
            const fontSize = Math.max(7, 10 / globalScale);
            ctx.font = `500 ${fontSize}px system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "bottom";
            ctx.fillStyle = "rgba(148, 163, 184, 0.75)";
            ctx.fillText(title, cluster.cx, cluster.cy - cluster.halfH - 4);
          }
        }
      },
      [hubNode, ringNodes, typeClusterNodes, gridClusters, resolveClusterLabel]
    );

    const paintNode = useCallback(
      (node: ForceGraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const x = node.x ?? 0;
        const y = node.y ?? 0;
        const r = graphNodeRadius(nodeVisualVal(node));

        if (highlightId === node.id) {
          ctx.beginPath();
          ctx.arc(x, y, r + 3, 0, Math.PI * 2);
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1.5 / globalScale;
          ctx.stroke();
        }

        if (node.isCollapsedHub) {
          ctx.beginPath();
          ctx.arc(x, y, r + 6, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(96, 165, 250, 0.4)";
          ctx.setLineDash([3 / globalScale, 2 / globalScale]);
          ctx.lineWidth = 1 / globalScale;
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
        ctx.fillStyle = node.color || "#60a5fa";
        ctx.globalAlpha = node.type === "article" ? 1 : 0.92;
        ctx.fill();
        ctx.globalAlpha = 1;

        const clusterSize = node.clusterSize ?? 1;
        const showLabel =
          node.type === "article" ||
          node.isCollapsedHub ||
          node.isTypeCluster ||
          (node.layoutRole === "grid" &&
            clusterSize <= 18 &&
            globalScale > 0.5) ||
          (node.layoutRole === "grid" &&
            clusterSize > 18 &&
            globalScale > 2.2) ||
          (node.layoutRole === "ring" && globalScale > 0.28) ||
          globalScale > 0.85;
        if (showLabel) {
          const name = displayName(node);
          const label = node.isTypeCluster
            ? truncateLabel(`${name} (${node.typeClusterCount ?? 0})`, 24)
            : node.isCollapsedHub && (node.collapsedChildCount ?? 0) > 0
              ? truncateLabel(`${name} (+${node.collapsedChildCount})`, 24)
              : truncateLabel(name, node.layoutRole === "grid" ? 22 : 18);
          const fontSize = Math.max(7, Math.min(11, 10 / globalScale));
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
      [highlightId, displayName, truncateLabel]
    );

    const paintPointerArea = useCallback(
      (node: ForceGraphNode, color: string, ctx: CanvasRenderingContext2D) => {
        const r = Math.max(4, graphNodeRadius(nodeVisualVal(node)) + 4);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, Math.PI * 2);
        ctx.fill();
      },
      []
    );

    const nodeLabel = useCallback(
      (node: ForceGraphNode) => displayName(node),
      [displayName]
    );

    if (!canvasReady || width <= 0 || height <= 0) {
      return (
        <div
          className="absolute inset-0 bg-slate-950/20"
          style={{ width, height: Math.max(height, 360) }}
        />
      );
    }

    return (
      <ForceGraph2D
        ref={fgRef}
        width={width}
        height={height}
        graphData={graphData}
        backgroundColor="rgba(2, 6, 23, 0)"
        nodeRelSize={1}
        nodeVal={(node: ForceGraphNode) => nodeVisualVal(node)}
        nodeLabel={nodeLabel}
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => "replace"}
        nodePointerAreaPaint={paintPointerArea}
        linkColor={() => "rgba(51, 65, 85, 0.22)"}
        linkWidth={0.35}
        linkDirectionalParticles={0}
        d3AlphaDecay={1}
        d3VelocityDecay={0.9}
        warmupTicks={0}
        cooldownTicks={0}
        enableNodeDrag={false}
        enableZoomInteraction
        enablePanInteraction
        onRenderFramePre={paintBackground}
        onEngineStop={handleEngineStop}
        onNodeClick={(node: ForceGraphNode) => onNodeClick?.(node)}
      />
    );
  }
);
