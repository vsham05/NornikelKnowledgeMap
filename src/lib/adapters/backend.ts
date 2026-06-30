import { getEntityColor } from "@/lib/graph";
import { parseQuery } from "@/lib/query";
import type {
  BackendExperiment,
  BackendGap,
  BackendGraph,
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
};

const NODE_SIZE: Record<string, number> = {
  Material: 7,
  Experiment: 8,
  Document: 4,
  Property: 5,
  Image: 3,
  RegimeParameter: 4,
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
  return {
    id: n.id,
    type,
    name: backendNodeName(n),
    val: NODE_SIZE[n.type] ?? 4,
    color: getEntityColor(type),
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
    UNDER_MODE: "under_mode",
    MEASURED: "measures",
    USES_SETUP: "uses_setup",
    CONDUCTED_BY: "conducted_by",
    CONCLUDES: "concludes",
    DESCRIBED_IN: "describes",
    HAS_PROPERTY: "measures",
    HAS_VALUE: "measures",
    TAGGED: "tagged",
    REFERENCES: "references",
    EMPLOYS: "employs",
  };
  return map[relation] ?? "references";
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
  return {
    experiment: {
      id: exp.id,
      type: "experiment",
      name: exp.regime
        ? `${exp.material ?? "Material"} — ${exp.regime}`
        : `Experiment ${exp.id.slice(0, 8)}`,
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
    material: {
      id: `mat-${exp.material}`,
      type: "material",
      name: exp.material ?? "Unknown",
      composition: "",
      category: "",
    },
    mode: {
      id: `mode-${exp.regime}`,
      type: "mode",
      name: exp.regime ?? exp.regime_type ?? "Unknown mode",
      category: exp.regime_type ?? "process",
    },
    properties: [],
    team: {
      id: "team-unknown",
      type: "team",
      name: "Research team",
      lab: "",
      lead: "",
      members: [],
    },
    relevance: 85,
    effectSummary: exp.conclusions ?? (exp.document ? `Source: ${exp.document}` : "See graph for details"),
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
  const docIds = new Set(
    graph.nodes.filter((n) => n.type === "Document").map((n) => n.id)
  );
  return backendGraphToFrontend({
    nodes: graph.nodes.filter((n) => n.type === "Document"),
    edges: graph.edges.filter((e) => docIds.has(e.source) && docIds.has(e.target)),
  });
}

function linkDocumentsStar(nodes: GraphNode[]): GraphEdge[] {
  if (nodes.length < 2) return [];
  const center = nodes[0];
  return nodes.slice(1).map((n, i) => ({
    id: `doc-link-${i}`,
    source: center.id,
    target: n.id,
    relation: "references" as const,
  }));
}

export async function backendSearch(query: string): Promise<SearchResult> {
  const parsed = parseQuery(query);

  const materialName = parsed.material;

  const [rag, graphSearch, gapsRes, materialExps, explore] = await Promise.all([
    backendApi.ragSearch(query).catch(() => null),
    backendApi.graphSearch(query).catch(() => ({ query, results: [], count: 0 })),
    backendApi.dataGaps().catch(() => ({ gaps: [], count: 0 })),
    materialName
      ? backendApi.experimentsByMaterial(materialName).catch(() => ({ experiments: [], count: 0 }))
      : Promise.resolve({ experiments: [], count: 0 }),
    backendApi.exploreGraph(80).catch(() => null),
  ]);

  const experiments: ExperimentResult[] = (materialExps.experiments ?? []).map(
    backendExperimentToResult
  );

  let graph = explore ? documentGraphFromExplore(explore) : { nodes: [], links: [] };

  if (graph.nodes.length > 1 && graph.links.length === 0) {
    graph = { nodes: graph.nodes, links: linkDocumentsStar(graph.nodes) };
  }

  void graphSearch;

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
    narrative: buildNarrative(rag, experiments, gaps),
    sources,
    confidence: rag?.confidence,
  };
}

function buildNarrative(
  rag: BackendRagResult | null,
  experiments: ExperimentResult[],
  gaps: DataGap[]
): string {
  const parts: string[] = [];

  if (rag?.answer) {
    parts.push(rag.answer);
  } else if (experiments.length > 0) {
    parts.push(`Found ${experiments.length} related experiment(s) in the knowledge graph.`);
  } else {
    parts.push(
      "No answer generated. Try re-ingesting your documents, then search again."
    );
  }

  // Gaps are shown in the sidebar — don't append to the answer text.
  return parts.join(" ");
}
