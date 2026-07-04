import type { GraphEdge, GraphNode } from "@/lib/types";
import { isTypeClusterNode, parseTypeClusterId } from "@/lib/graphHierarchy";

function linkEndpoints(link: GraphEdge): [string, string] {
  return [String(link.source), String(link.target)];
}

/**
 * Progressive disclosure: document hubs → type capsules → entity nodes.
 * Avoids laying out or rendering thousands of entities at once.
 */
export function filterNodesForLayout(
  nodes: GraphNode[],
  links: GraphEdge[],
  expandedDocIds: Set<string>,
  expandedTypeKeys: Set<string>
): { nodes: GraphNode[]; links: GraphEdge[] } {
  const articles = nodes.filter((n) => n.type === "article");
  if (articles.length === 0) {
    return { nodes: [...nodes], links: [...links] };
  }

  if (expandedDocIds.size === 0) {
    return { nodes: articles, links: [] };
  }

  const keep = new Set<string>(articles.map((a) => a.id));

  for (const node of nodes) {
    if (node.type === "article") continue;

    if (isTypeClusterNode(node)) {
      const docId = node.hubId ?? node.documentId;
      if (!docId || !expandedDocIds.has(docId)) continue;
      const parsed = parseTypeClusterId(node.id);
      if (parsed && expandedTypeKeys.has(`${parsed.documentId}:${parsed.entityType}`)) {
        continue;
      }
      keep.add(node.id);
      continue;
    }

    const hub = node.hubId ?? node.documentId;
    if (!hub || !expandedDocIds.has(hub)) continue;

    const typeKey = `${hub}:${node.type}`;
    if (expandedTypeKeys.has(typeKey)) keep.add(node.id);
  }

  for (const link of links) {
    const [a, b] = linkEndpoints(link);
    if (keep.has(a) && keep.has(b)) continue;
    if (expandedDocIds.has(a) || expandedDocIds.has(b)) {
      if (keep.has(a)) keep.add(b);
      if (keep.has(b)) keep.add(a);
    }
  }

  const filteredNodes = nodes.filter((n) => keep.has(n.id));
  const filteredLinks = links.filter((l) => {
    const [a, b] = linkEndpoints(l);
    return keep.has(a) && keep.has(b);
  });

  return { nodes: filteredNodes, links: filteredLinks };
}
