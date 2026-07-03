import type { BackendDocument } from "@/lib/api/backend";
import type { Article, Entity, GraphNode, Material, Team, Facility } from "@/lib/types";
import { parseMaterialComponents } from "@/lib/materialComponents";

function inferFormat(filePath: string): Article["format"] {
  const lower = filePath.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) return "web";
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".docx") || lower.endsWith(".doc")) return "word";
  return "web";
}

export function graphNodeToEntity(node: GraphNode): Entity {
  if (node.type === "material") {
    const components =
      node.components?.length
        ? node.components
        : parseMaterialComponents(node.name);
    return {
      id: node.id,
      type: "material",
      name: node.name,
      composition: "",
      category: "",
      components,
    } satisfies Material;
  }

  if (node.type === "team") {
    const members = node.members ?? [];
    return {
      id: node.id,
      type: "team",
      name: node.name,
      lab: node.name,
      lead: members[0] ?? "",
      members,
    } satisfies Team;
  }

  if (node.type === "facility") {
    return {
      id: node.id,
      type: "facility",
      name: node.name,
      country: node.country,
      facilityType: node.facilityType,
    } satisfies Facility;
  }

  return {
    id: node.id,
    type: node.type,
    name: node.name,
  } as Entity;
}

export function backendDocumentToArticle(
  doc: BackendDocument,
  node: GraphNode
): Article {
  const filePath = doc.file_path || doc.canonical_source || "";
  const isUrl = filePath.startsWith("http");

  return {
    id: node.id,
    type: "article",
    name: doc.title || node.name,
    source: "internal",
    format: inferFormat(filePath),
    authors: doc.authors ?? [],
    publishedAt: doc.year ? String(doc.year) : doc.created_at?.slice(0, 10) ?? "",
    textLayer: "",
    url: isUrl ? filePath : undefined,
    description: filePath || undefined,
  };
}
