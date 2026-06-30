import type { BackendDocument } from "@/lib/api/backend";
import type { Article, Entity, GraphNode } from "@/lib/types";

function inferFormat(filePath: string): Article["format"] {
  const lower = filePath.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) return "web";
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".docx") || lower.endsWith(".doc")) return "word";
  return "web";
}

export function graphNodeToEntity(node: GraphNode): Entity {
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
  const chunks = doc.chunks_count ?? 0;
  const images = doc.images_count ?? 0;

  return {
    id: node.id,
    type: "article",
    name: doc.title || node.name,
    source: "internal",
    format: inferFormat(filePath),
    authors: doc.authors ?? [],
    publishedAt: doc.year ? String(doc.year) : doc.created_at?.slice(0, 10) ?? "—",
    textLayer:
      chunks > 0
        ? `Indexed document with ${chunks} text chunk${chunks === 1 ? "" : "s"}${
            images > 0 ? ` and ${images} image${images === 1 ? "" : "s"}` : ""
          }. Search the knowledge base to see relevant excerpts.`
        : "Document indexed in the knowledge graph.",
    url: isUrl ? filePath : undefined,
    description: filePath || undefined,
  };
}
