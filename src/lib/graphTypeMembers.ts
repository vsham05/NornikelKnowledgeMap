import { backendGraphToFrontend } from "@/lib/adapters/backend";
import { backendApi, GRAPH_TYPE_PAGE_LIMIT } from "@/lib/api/backend";
import { entityTypeToNeo4jLabel } from "@/lib/graphHierarchy";
import type { EntityType, GraphNode } from "@/lib/types";

/** Load every entity of a type for a document (paginated on the backend). */
export async function fetchAllTypeClusterMembers(
  documentId: string,
  entityType: EntityType
): Promise<{ nodes: GraphNode[]; total: number }> {
  const neo4jLabel = entityTypeToNeo4jLabel(entityType);
  if (!neo4jLabel) return { nodes: [], total: 0 };

  const pageSize = GRAPH_TYPE_PAGE_LIMIT;
  let offset = 0;
  const allNodes: GraphNode[] = [];
  let total = 0;

  while (true) {
    const page = await backendApi.documentEntitiesByType(
      documentId,
      neo4jLabel,
      pageSize,
      offset
    );
    const graph = backendGraphToFrontend({ nodes: page.nodes, edges: page.edges });
    for (const node of graph.nodes) {
      if (node.type !== entityType) continue;
      allNodes.push({
        ...node,
        hubId: documentId,
        documentId,
      });
    }
    total = page.total;
    if (!page.has_more) break;
    offset += pageSize;
  }

  allNodes.sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
  );

  return { nodes: allNodes, total };
}
