import { getEntityColor } from "@/lib/graph";
import { backendNodeType } from "@/lib/adapters/backend";
import type { EntityType, GraphEdge, GraphNode } from "@/lib/types";

export type DocumentTypeSummary = {
  label: string;
  count: number;
};

export type DocumentEntitySummary = {
  document_id: string;
  total_entities: number;
  types: DocumentTypeSummary[];
};

export type DocumentEntityPage = {
  document_id: string;
  entity_label: string;
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
  nodes: Array<{ id: string; label: string; type: string; properties?: Record<string, unknown> }>;
  edges: Array<{ source: string; target: string; type: string }>;
};

const NEO4J_TO_ENTITY: Record<string, EntityType> = {
  Material: "material",
  Experiment: "experiment",
  Document: "article",
  Property: "property",
  RegimeParameter: "mode",
  Team: "team",
  Process: "process",
  Equipment: "equipment",
  Facility: "facility",
  Expert: "expert",
  FigureGallery: "figures",
};

const ENTITY_TO_NEO4J: Partial<Record<EntityType, string>> = {
  material: "Material",
  experiment: "Experiment",
  property: "Property",
  mode: "RegimeParameter",
  team: "Team",
  process: "Process",
  equipment: "Equipment",
  facility: "Facility",
  expert: "Expert",
  figures: "FigureGallery",
};

export function neo4jLabelToEntityType(label: string): EntityType {
  return NEO4J_TO_ENTITY[label] ?? backendNodeType(label);
}

export function entityTypeToNeo4jLabel(type: EntityType): string | null {
  return ENTITY_TO_NEO4J[type] ?? null;
}

export function typeClusterId(documentId: string, entityType: EntityType): string {
  return `typecluster:${documentId}:${entityType}`;
}

export function parseTypeClusterId(id: string): { documentId: string; entityType: EntityType } | null {
  if (!id.startsWith("typecluster:")) return null;
  const parts = id.split(":");
  if (parts.length < 3) return null;
  const documentId = parts[1];
  const entityType = parts.slice(2).join(":") as EntityType;
  return { documentId, entityType };
}

export function isTypeClusterNode(node: Pick<GraphNode, "id">): boolean {
  return node.id.startsWith("typecluster:");
}

export function expandedTypeKey(documentId: string, entityType: EntityType): string {
  return `${documentId}:${entityType}`;
}

export function buildTypeClusterGraph(
  documentId: string,
  types: DocumentTypeSummary[],
  typeLabel: (type: EntityType) => string
): { nodes: GraphNode[]; links: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const links: GraphEdge[] = [];

  for (const entry of types) {
    if (entry.count <= 0) continue;
    const entityType = neo4jLabelToEntityType(entry.label);
    const id = typeClusterId(documentId, entityType);
    nodes.push({
      id,
      type: entityType,
      name: typeLabel(entityType),
      val: Math.max(10, Math.min(18, 8 + Math.log10(entry.count + 1) * 4)),
      color: getEntityColor(entityType),
      documentId,
      hubId: documentId,
      isTypeCluster: true,
      typeClusterCount: entry.count,
    });
    links.push({
      id: `hub-${documentId}-${entityType}`,
      source: documentId,
      target: id,
      relation: "describes",
    });
  }

  return { nodes, links };
}

export function removeDocumentHierarchy(
  snapshot: { nodes: GraphNode[]; links: GraphEdge[] },
  documentId: string
): { nodes: GraphNode[]; links: GraphEdge[] } {
  const drop = new Set<string>([documentId]);
  for (const node of snapshot.nodes) {
    if (node.id.startsWith(`typecluster:${documentId}:`)) drop.add(node.id);
    if (node.documentId === documentId && node.type !== "article") drop.add(node.id);
    if (node.hubId === documentId && node.type !== "article") drop.add(node.id);
  }
  return {
    nodes: snapshot.nodes.filter((n) => !drop.has(n.id)),
    links: snapshot.links.filter((l) => {
      const src = String(l.source);
      const tgt = String(l.target);
      return !drop.has(src) && !drop.has(tgt);
    }),
  };
}

/** Entity nodes belonging to a type cluster already present in the graph snapshot. */
export function snapshotTypeClusterMembers(
  nodes: GraphNode[],
  documentId: string,
  entityType: EntityType
): GraphNode[] {
  return nodes
    .filter(
      (n) =>
        !isTypeClusterNode(n) &&
        n.type === entityType &&
        (n.hubId === documentId || n.documentId === documentId)
    )
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}
