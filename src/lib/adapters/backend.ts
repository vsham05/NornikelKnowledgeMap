import { translate, type Locale } from "@/lib/i18n/translations";
import { getEntityColor } from "@/lib/graph";
import {
  mergedMaterialLabel,
  parseMaterialComponents,
} from "@/lib/materialComponents";
import { parseQuery, parsedToStructured, structuredToBackend } from "@/lib/query";
import type { StructuredFilters } from "@/lib/types";
import type {
  BackendExperiment,
  BackendGap,
  BackendGraph,
  BackendGraphNode,
  BackendRagResult,
} from "@/lib/api/backend";
import type {
  DataGap,
  EntityType,
  ExperimentResult,
  GraphEdge,
  GraphNode,
  ParsedQuery,
  SearchResult,
} from "@/lib/types";
import { backendApi } from "@/lib/api/backend";

const TYPE_MAP: Record<string, EntityType> = {
  Material: "material",
  Experiment: "experiment",
  Document: "article",
  Property: "property",
  Image: "article",
  RegimeParameter: "mode",
  Team: "team",
  Process: "process",
  Equipment: "equipment",
  Facility: "facility",
  Expert: "expert",
};

const NODE_SIZE: Record<string, number> = {
  Material: 8,
  Experiment: 9,
  Document: 12,
  Property: 6,
  Image: 4,
  RegimeParameter: 7,
  Team: 7,
  Process: 8,
  Equipment: 7,
  Facility: 6,
  Expert: 6,
};

export function backendNodeType(label: string): EntityType {
  return TYPE_MAP[label] ?? "topic";
}

function backendNodeName(node: BackendGraphNode): string {
  const label = node.label?.trim();
  if (label) return label;
  const id = node.id?.trim();
  if (id) return id.length > 12 ? `${id.slice(0, 8)}…` : id;
  return "Unknown";
}

function toGraphNode(n: BackendGraphNode): GraphNode {
  const type = backendNodeType(n.type);
  const name = backendNodeName(n);
  const aliases = Array.isArray(n.properties?.aliases)
    ? (n.properties!.aliases as string[]).filter(Boolean)
    : [];
  const members = Array.isArray(n.properties?.members)
    ? (n.properties!.members as string[]).filter(Boolean)
    : undefined;
  const country =
    typeof n.properties?.country === "string" ? n.properties.country : undefined;
  const facilityType =
    typeof n.properties?.facility_type === "string"
      ? n.properties.facility_type
      : undefined;
  const components =
    type === "material" ? parseMaterialComponents(name, aliases) : undefined;
  return {
    id: n.id,
    type,
    name:
      type === "material" && components && components.length > 1
        ? mergedMaterialLabel(components)
        : name,
    val: NODE_SIZE[n.type] ?? 4,
    color: getEntityColor(type),
    components,
    ...(type === "team" && members ? { members } : {}),
    ...(type === "facility"
      ? { country, facilityType }
      : {}),
  };
}

export function backendGraphToFrontend(graph: BackendGraph): {
  nodes: GraphNode[];
  links: GraphEdge[];
} {
  const nodes: GraphNode[] = graph.nodes
    .filter((n) => Boolean(n.id))
    .map(toGraphNode);

  const links: GraphEdge[] = graph.edges.map((e, i) => ({
    id: `edge-${i}-${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    relation: mapRelation(e.type),
  }));

  return { nodes, links };
}

function mapRelation(relation: string): GraphEdge["relation"] {
  const map: Record<string, GraphEdge["relation"]> = {
    USES_MATERIAL: "uses_material",
    MENTIONS_MATERIAL: "uses_material",
    UNDER_MODE: "under_mode",
    HAS_REGIME_PARAM: "under_mode",
    HAS_TOPIC: "tagged",
    MEASURED: "measures",
    HAS_PROPERTY: "measures",
    USES_SETUP: "uses_setup",
    CONDUCTED_BY: "conducted_by",
    AUTHORED: "conducted_by",
    AUTHORED_BY: "conducted_by",
    MEMBER_OF: "conducted_by",
    CONCLUDES: "concludes",
    DESCRIBED_IN: "describes",
    DESCRIBES_PROCESS: "describes",
    FROM_FACILITY: "references",
    MENTIONS_EQUIPMENT: "employs",
    USES_EQUIPMENT: "employs",
    USES_PROCESS: "employs",
    PROCESSED_IN: "processed_in",
    HAS_VALUE: "measures",
    TAGGED: "tagged",
    REFERENCES: "references",
    EMPLOYS: "employs",
  };
  return map[relation] ?? "references";
}

const RELATION_LABELS: Record<GraphEdge["relation"], string> = {
  describes: "from document",
  uses_material: "uses material",
  under_mode: "mode / parameter",
  measures: "measures",
  uses_setup: "uses setup",
  conducted_by: "authored by",
  concludes: "concludes",
  tagged: "topic",
  references: "references",
  employs: "employs",
  processed_in: "processed in",
};

export function relationLabel(
  relation: GraphEdge["relation"],
  locale?: Locale
): string {
  if (locale) {
    return translate(locale, `relation.${relation}`);
  }
  return RELATION_LABELS[relation] ?? relation;
}

export function backendGapsToFrontend(gaps: BackendGap[]): DataGap[] {
  return gaps.map((g) => ({
    material: g.material,
    mode: g.regime ?? g.gap_type,
    property: g.property ?? g.gap_type,
    priority:
      g.gap_type === "no_experiments" || g.gap_type === "no_measured_properties"
        ? "high"
        : "medium",
    reason: g.description,
  }));
}

export function backendExperimentToResult(exp: BackendExperiment): ExperimentResult {
  const label = [exp.material, exp.regime].filter(Boolean).join(" — ");
  return {
    experiment: {
      id: exp.id,
      type: "experiment",
      name: label || exp.id.slice(0, 12),
      code: exp.id.slice(0, 12),
      startedAt: "",
      status: "completed",
      materialId: "",
      modeId: "",
      setupId: "",
      teamId: "",
      propertyIds: [],
      articleIds: [],
      measurements: [],
      description: exp.conclusions ?? exp.document ?? undefined,
    },
    material: exp.material
      ? {
          id: `mat-${exp.material}`,
          type: "material",
          name: exp.material,
          composition: "",
          category: "",
        }
      : undefined,
    mode: exp.regime || exp.regime_type
      ? {
          id: `mode-${exp.regime ?? exp.regime_type}`,
          type: "mode",
          name: exp.regime ?? exp.regime_type ?? "",
          category: exp.regime_type ?? "process",
        }
      : undefined,
    properties: [],
    relevance: 85,
    effectSummary:
      exp.conclusions ?? (exp.document ? `Source: ${exp.document}` : ""),
    conclusion: exp.conclusions
      ? {
          id: `concl-${exp.id}`,
          type: "conclusion",
          name: "Conclusion",
          summary: exp.conclusions,
          confidence: "medium",
          effect: "neutral",
        }
      : undefined,
  };
}

function documentGraphFromExplore(graph: BackendGraph): {
  nodes: GraphNode[];
  links: GraphEdge[];
} {
  return backendGraphToFrontend(graph);
}

export async function backendSearch(
  query: string,
  documentId?: string,
  structuredFilters?: StructuredFilters
): Promise<SearchResult> {
  const parsed = parseQuery(query);
  const structured = {
    ...structuredToBackend(parsedToStructured(parsed)),
    ...structuredToBackend(structuredFilters ?? {}),
  };
  const cleanStructured = Object.fromEntries(
    Object.entries(structured).filter(([, v]) => v != null && v !== "")
  );

  const materialName = structuredFilters?.material ?? parsed.material;

  const [rag, graphSearch, gapsRes, materialExps, explore, structuredHits] = await Promise.all([
    backendApi.ragSearch(query, documentId, cleanStructured).catch(() => null),
    backendApi.graphSearch(query).catch(() => ({ query, results: [], count: 0 })),
    backendApi.dataGaps().catch(() => ({ gaps: [], count: 0 })),
    materialName
      ? backendApi.experimentsByMaterial(materialName).catch(() => ({ experiments: [], count: 0 }))
      : Promise.resolve({ experiments: [], count: 0 }),
    backendApi.exploreGraph(300).catch(() => null),
    Object.keys(cleanStructured).length
      ? backendApi.structuredQuery(cleanStructured).catch(() => null)
      : Promise.resolve(null),
  ]);

  const experiments: ExperimentResult[] = (materialExps.experiments ?? []).map(
    backendExperimentToResult
  );

  const graph = explore ? documentGraphFromExplore(explore) : { nodes: [], links: [] };

  void graphSearch;
  void structuredHits;

  const gaps = backendGapsToFrontend(gapsRes.gaps ?? []).slice(0, 12);

  const sources: import("@/lib/types").SourceExcerpt[] = (rag?.sources ?? []).map((s) => ({
    index: s.index,
    text: s.text,
    documentId: s.document_id,
    title: s.title,
  }));

  return {
    query,
    parsed,
    experiments,
    relatedEntities: [],
    graph,
    gaps,
    narrative: buildNarrative(rag, experiments, gaps, structuredHits),
    sources,
    confidence: rag?.confidence,
    needsDisambiguation: rag?.needs_disambiguation,
    documentCandidates: rag?.document_candidates?.map((c) => ({
      documentId: c.document_id,
      title: c.title,
      score: c.score,
    })),
    retrievalScope: rag?.retrieval_scope
      ? {
          mode: rag.retrieval_scope.mode,
          filterDocumentIds: rag.retrieval_scope.filter_document_ids,
          filterDocumentTitles: rag.retrieval_scope.filter_document_titles,
          filtersApplied: rag.retrieval_scope.filters_applied,
          graphMatchCount: rag.retrieval_scope.graph_match_count,
        }
      : undefined,
  };
}

function buildNarrative(
  rag: BackendRagResult | null,
  experiments: ExperimentResult[],
  gaps: DataGap[],
  structuredHits: { count?: number } | null
): string {
  const parts: string[] = [];

  if (rag?.answer) {
    parts.push(rag.answer);
  } else if (experiments.length > 0) {
    parts.push(`Found ${experiments.length} related experiment(s) in the knowledge graph.`);
  } else if (structuredHits?.count) {
    parts.push(
      `Knowledge graph: ${structuredHits.count} matching experiment(s) for your structured filters.`
    );
  } else {
    parts.push(
      "No answer generated. Try re-ingesting documents or refining filters, then search again."
    );
  }

  return parts.join(" ");
}
