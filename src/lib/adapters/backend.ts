import { translate, type Locale } from "@/lib/i18n/translations";
import { getEntityColor } from "@/lib/graph";
import {
  mergedMaterialLabel,
  parseMaterialComponents,
} from "@/lib/materialComponents";
import { deduplicateGraphEntities } from "@/lib/graphDedup";
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
import { backendApi, GRAPH_DOCUMENT_LIMIT, GRAPH_OVERVIEW_LIMIT } from "@/lib/api/backend";

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
  FigureGallery: "figures",
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
  FigureGallery: 8,
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

function parseFigureItems(
  properties: Record<string, unknown> | undefined
): Array<Record<string, unknown>> {
  if (!properties) return [];
  if (Array.isArray(properties.items)) {
    return properties.items as Array<Record<string, unknown>>;
  }
  const raw = properties.items_json;
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (Array.isArray(parsed)) {
        return parsed as Array<Record<string, unknown>>;
      }
    } catch {
      /* ignore */
    }
  }
  return [];
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
  const rawItems = parseFigureItems(n.properties);
  const figures =
    type === "figures"
      ? (rawItems as Array<Record<string, unknown>>).map((item) => ({
          id: String(item.id ?? ""),
          caption: item.caption ? String(item.caption) : undefined,
          page_number:
            typeof item.page_number === "number" ? item.page_number : undefined,
          image_type: item.image_type ? String(item.image_type) : undefined,
          storage_key: item.storage_key ? String(item.storage_key) : undefined,
        }))
      : undefined;
  const documentId =
    typeof n.properties?.document_id === "string"
      ? n.properties.document_id
      : type === "figures" && n.id.includes(":figures")
        ? n.id.replace(/:figures$/, "")
        : undefined;
  const regimeName =
    typeof n.properties?.regime_name === "string" ? n.properties.regime_name : undefined;
  const regimeDescription =
    typeof n.properties?.regime_description === "string"
      ? n.properties.regime_description
      : undefined;
  const rawConclusions = n.properties?.conclusions;
  const conclusionText = Array.isArray(rawConclusions)
    ? rawConclusions.map(String).filter(Boolean).join("; ")
    : typeof rawConclusions === "string"
      ? rawConclusions
      : undefined;
  const statusRaw =
    typeof n.properties?.status === "string" ? n.properties.status.toLowerCase() : "";
  const experimentStatus =
    statusRaw === "completed" || statusRaw === "ongoing" || statusRaw === "planned"
      ? statusRaw
      : undefined;
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
    ...(type === "figures"
      ? {
          figures,
          documentId,
          imageCount:
            typeof n.properties?.image_count === "number"
              ? n.properties.image_count
              : figures?.length,
          typeSummary:
            typeof n.properties?.type_summary === "string"
              ? n.properties.type_summary
              : undefined,
        }
      : {}),
    ...(type === "experiment"
      ? {
          regimeName,
          regimeDescription,
          conclusionText,
          experimentStatus,
        }
      : {}),
    ...(type === "property"
      ? {
          sampleValue:
            typeof n.properties?.sample_value === "string"
              ? n.properties.sample_value
              : undefined,
          sampleUnit:
            typeof n.properties?.sample_unit === "string"
              ? n.properties.sample_unit
              : undefined,
        }
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

  const deduped = deduplicateGraphEntities(nodes, links);
  return { nodes: deduped.nodes, links: deduped.links };
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
    HAS_FIGURES: "has_figures",
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
  has_figures: "has figures",
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

function buildSearchResultFromRag(
  query: string,
  parsed: ParsedQuery,
  rag: BackendRagResult | null,
  structuredHits: { count?: number } | null = null,
  experiments: ExperimentResult[] = []
): SearchResult {
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
    graph: { nodes: [], links: [] },
    gaps: [],
    narrative: buildNarrative(rag, experiments, structuredHits),
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
    graphMatchIds: [],
    structuredExperiments: [],
  };
}

async function loadSearchEnrichment(
  query: string,
  documentId: string | undefined,
  cleanStructured: Record<string, string>,
  materialName: string | undefined
) {
  const [graphSearch, materialExps, explore, structuredHits] = await Promise.all([
    backendApi.graphSearch(query, 8).catch(() => ({ query, results: [], count: 0 })),
    materialName
      ? backendApi.experimentsByMaterial(materialName).catch(() => ({ experiments: [], count: 0 }))
      : Promise.resolve({ experiments: [], count: 0 }),
    backendApi.exploreGraph(documentId ? GRAPH_DOCUMENT_LIMIT : GRAPH_OVERVIEW_LIMIT, documentId).catch(() => null),
    Object.keys(cleanStructured).length
      ? backendApi.structuredQuery(cleanStructured).catch(() => null)
      : Promise.resolve(null),
  ]);

  const experiments: ExperimentResult[] = (materialExps.experiments ?? []).map(
    backendExperimentToResult
  );
  const graph = explore ? documentGraphFromExplore(explore) : { nodes: [], links: [] };
  const graphMatchIds = (graphSearch.results ?? [])
    .map((r) => r.id)
    .filter((id): id is string => Boolean(id));
  const structuredExperiments = (structuredHits?.experiments ?? []).map((row) => ({
    experiment_id: row.experiment_id as string | undefined,
    material: row.material as string | undefined,
    process: row.process as string | undefined,
    regime: row.regime as string | undefined,
    document_id: row.document_id as string | undefined,
    document_title: row.document_title as string | undefined,
    year: typeof row.year === "number" ? row.year : undefined,
  }));

  return { experiments, graph, graphMatchIds, structuredHits, structuredExperiments };
}

export function mergeSearchEnrichment(
  base: SearchResult,
  enrichment: Awaited<ReturnType<typeof loadSearchEnrichment>>
): SearchResult {
  const experiments =
    enrichment.experiments.length > 0 ? enrichment.experiments : base.experiments;
  return {
    ...base,
    experiments,
    graph: enrichment.graph.nodes.length > 0 ? enrichment.graph : base.graph,
    graphMatchIds: enrichment.graphMatchIds,
    structuredExperiments: enrichment.structuredExperiments,
    narrative:
      base.narrative ||
      (experiments.length > 0
        ? `Found ${experiments.length} related experiment(s) in the knowledge graph.`
        : base.narrative),
  };
}

export async function backendSearch(
  query: string,
  documentId?: string,
  structuredFilters?: StructuredFilters,
  onRagComplete?: (partial: SearchResult) => void
): Promise<SearchResult> {
  const parsed = parseQuery(query);
  const structured = {
    ...structuredToBackend(parsedToStructured(parsed)),
    ...structuredToBackend(structuredFilters ?? {}),
  };
  const cleanStructured = Object.fromEntries(
    Object.entries(structured).filter(([, v]) => v != null && v !== "")
  ) as Record<string, string>;

  const materialName = structuredFilters?.material ?? parsed.material;

  const rag = await backendApi.ragSearch(query, documentId, cleanStructured).catch(() => null);
  const partial = buildSearchResultFromRag(query, parsed, rag);
  onRagComplete?.(partial);

  const enrichment = await loadSearchEnrichment(
    query,
    documentId,
    cleanStructured,
    materialName
  );

  return mergeSearchEnrichment(partial, enrichment);
}

function buildNarrative(
  rag: BackendRagResult | null,
  experiments: ExperimentResult[],
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
