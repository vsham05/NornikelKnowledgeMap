import type { GraphEdge, GraphNode } from "@/lib/types";

export interface NodeConnection {
  node: GraphNode;
  relation: GraphEdge["relation"];
  direction: "out" | "in";
}

function linkEndpoint(
  endpoint: string | { id?: string }
): string {
  if (typeof endpoint === "string") return endpoint;
  return String(endpoint.id ?? endpoint);
}

export function getNodeConnections(
  nodeId: string,
  nodes: GraphNode[],
  links: GraphEdge[]
): NodeConnection[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const seen = new Set<string>();
  const connections: NodeConnection[] = [];

  for (const link of links) {
    const src = linkEndpoint(link.source as string | { id?: string });
    const tgt = linkEndpoint(link.target as string | { id?: string });

    if (src === nodeId) {
      const key = `out|${tgt}|${link.relation}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const node = byId.get(tgt);
      if (node) connections.push({ node, relation: link.relation, direction: "out" });
    } else if (tgt === nodeId) {
      const key = `in|${src}|${link.relation}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const node = byId.get(src);
      if (node) connections.push({ node, relation: link.relation, direction: "in" });
    }
  }

  connections.sort((a, b) => {
    const byType = a.node.type.localeCompare(b.node.type);
    if (byType !== 0) return byType;
    return a.node.name.localeCompare(b.node.name, undefined, { sensitivity: "base" });
  });

  return connections;
}
