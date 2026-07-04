import type { GraphEdge, GraphNode } from "@/lib/types";

function linkKey(link: GraphEdge): string {
  const src = String(link.source);
  const tgt = String(link.target);
  return `${src}\0${tgt}\0${link.relation ?? ""}`;
}

/** Merge two graph snapshots without duplicating nodes or edges. */
export function mergeGraphSnapshots(
  base: { nodes: GraphNode[]; links: GraphEdge[] },
  addition: { nodes: GraphNode[]; links: GraphEdge[] }
): { nodes: GraphNode[]; links: GraphEdge[] } {
  const nodeMap = new Map(base.nodes.map((n) => [n.id, n]));
  for (const node of addition.nodes) {
    nodeMap.set(node.id, node);
  }
  const linkMap = new Map(base.links.map((l) => [linkKey(l), l]));
  for (const link of addition.links) {
    linkMap.set(linkKey(link), link);
  }
  return {
    nodes: [...nodeMap.values()],
    links: [...linkMap.values()],
  };
}
