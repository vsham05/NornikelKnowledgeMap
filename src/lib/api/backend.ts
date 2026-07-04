const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export function figureImageUrl(documentId: string, imageId: string): string {
  return `${BACKEND_URL}/api/v1/ingest/documents/${encodeURIComponent(documentId)}/images/${encodeURIComponent(imageId)}`;
}

export class BackendError extends Error {
  constructor(
    message: string,
    public status?: number
  ) {
    super(message);
    this.name = "BackendError";
  }
}

async function backendFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      headers: {
        ...init?.headers,
      },
    });
  } catch {
    throw new BackendError(
      `Cannot reach backend at ${BACKEND_URL}. Is FastAPI running?`
    );
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let message = text || res.statusText;
    try {
      const json = JSON.parse(text) as { detail?: string | { msg?: string }[] };
      if (typeof json.detail === "string") message = json.detail;
      else if (Array.isArray(json.detail) && json.detail[0]?.msg) {
        message = json.detail.map((d) => d.msg).join("; ");
      }
    } catch {
      // use raw text
    }
    throw new BackendError(message || `Request failed (${res.status})`, res.status);
  }

  return res.json() as Promise<T>;
}

export async function checkBackendHealth(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  const init: RequestInit = { signal: controller.signal, cache: "no-store" };

  try {
    const health = await fetch(`${BACKEND_URL}/health`, init);
    if (health.ok) return true;
    const stats = await fetch(`${BACKEND_URL}/api/v1/graph/stats`, init);
    return stats.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export interface BackendGraphNode {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, unknown>;
}

export interface BackendGraphEdge {
  source: string;
  target: string;
  type: string;
}

export const GRAPH_OVERVIEW_LIMIT = 3_000;
/** Max entities fetched per type when drilling into a large document. */
export const GRAPH_TYPE_PAGE_LIMIT = 500;
/** Legacy full-document fetch — avoid for large PDFs; prefer type drill-down. */
export const GRAPH_DOCUMENT_LIMIT = 10_000;

export interface BackendGraph {
  nodes: BackendGraphNode[];
  edges: BackendGraphEdge[];
}

export interface BackendStats {
  materials?: number;
  experiments?: number;
  documents?: number;
  properties?: number;
  images?: number;
  teams?: number;
  processes?: number;
  equipments?: number;
  facilities?: number;
  experts?: number;
  regimeparameters?: number;
  edges?: number;
  regime_types?: Record<string, number>;
  experiment_status?: {
    completed?: number;
    ongoing?: number;
    planned?: number;
  };
}

export interface BackendDocument {
  id?: string;
  title?: string;
  document_type?: string;
  authors?: string[];
  year?: number | null;
  file_path?: string;
  canonical_source?: string;
  chunks_count?: number;
  images_count?: number;
  created_at?: string;
  images?: Array<{ id?: string; caption?: string; description?: string }>;
  experiments?: Array<{ experiment_id?: string; regime?: string; material?: string }>;
}

export interface BackendRetrievalScope {
  mode: "full_corpus" | "explicit_document" | "structured_filters" | "structured_fallback";
  filter_document_ids?: string[];
  filter_document_titles?: string[];
  filters_applied?: Record<string, unknown>;
  graph_match_count?: number;
}

export interface BackendRagResult {
  query: string;
  answer: string | null;
  document_ids: string[];
  experiment_ids?: string[];
  confidence: number;
  sources?: BackendSourceExcerpt[];
  needs_disambiguation?: boolean;
  document_candidates?: BackendDocumentCandidate[];
  retrieval_scope?: BackendRetrievalScope;
}

export interface BackendDocumentCandidate {
  document_id: string;
  title?: string | null;
  score?: number;
}

export interface BackendSourceExcerpt {
  index: number;
  text: string;
  document_id: string;
  title?: string | null;
  score?: number | null;
}

export interface BackendGap {
  material: string;
  gap_type: string;
  description: string;
  regime?: string;
  property?: string;
}

export interface BackendExperimentDetails {
  id?: string;
  regime_name?: string;
  regime_description?: string;
  regime_type?: string;
  conclusions?: string | string[];
  status?: string;
  material_name?: string;
  document_title?: string;
  created_at?: string;
  regime_parameters?: Array<{ name?: string; value?: string; unit?: string }>;
  measured_properties?: Array<{
    name?: string;
    value?: string | number;
    unit?: string;
    category?: string;
  }>;
}

export interface BackendPropertyDetails {
  canonical_name?: string;
  display_label?: string;
  category?: string;
  unit?: string;
  measurements?: Array<{
    source?: string;
    experiment_id?: string;
    experiment_name?: string;
    material_id?: string;
    material_name?: string;
    document_title?: string;
    value?: string | number;
    unit?: string;
    source_text?: string;
  }>;
}

export interface BackendExperiment {
  id: string;
  regime?: string;
  regime_type?: string;
  material?: string;
  document?: string;
  conclusions?: string;
}

export interface BackendContradiction {
  material: string;
  property: string;
  value_a: string;
  value_b: string;
  experiment_a?: string;
  experiment_b?: string;
  source_a?: string;
  source_b?: string;
  description: string;
}

export interface StructuredFiltersPayload {
  material?: string;
  material_class?: string;
  process?: string;
  geography?: string;
  year_from?: number;
  year_to?: number;
  property_name?: string;
  value_min?: number;
  value_max?: number;
}

export interface BackendStructuredResult {
  count: number;
  experiments: Array<Record<string, unknown>>;
  documents: Array<Record<string, unknown>>;
}

export interface IngestTask {
  task_id: string;
  status: string;
  message: string;
}

export interface IngestTaskStatus {
  task_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;
  message: string;
  ingest_llm_provider?: "local" | "yandex" | null;
  ingest_llm_model?: string | null;
  result?: Record<string, unknown>;
  error?: string | null;
}

export type LlmProvider = "local" | "yandex";

export interface YandexModelOption {
  id: string;
  label: string;
  context_tokens: number;
  extraction_chars: number;
  tags: string[];
  moderation_risk: boolean;
  notes: string;
  recommended: boolean;
}

export interface LlmConfig {
  provider: LlmProvider;
  local_model: string;
  yandex_model: string;
  yandex_models: YandexModelOption[];
  yandex_recommended: string;
  yandex_ready: boolean;
  yandex_moderation_risk?: boolean;
  extraction_max_chars?: number;
  effective_model: string;
}

export const backendApi = {
  health: () => backendFetch<{ status: string }>("/health"),

  getLlmConfig: () => backendFetch<LlmConfig>("/api/v1/config/llm"),

  setLlmProvider: (provider: LlmProvider) =>
    backendFetch<LlmConfig>("/api/v1/config/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    }),

  setYandexModel: (model: string) =>
    backendFetch<LlmConfig>("/api/v1/config/llm/yandex-model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }),

  graphStats: () => backendFetch<BackendStats>("/api/v1/graph/stats"),

  enrichAllDocuments: () =>
    backendFetch<{ processed: number; enriched: number }>("/api/v1/graph/enrich-all", {
      method: "POST",
    }),

  exploreGraph: (limit = GRAPH_OVERVIEW_LIMIT, documentId?: string, hubOnly = false) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (documentId) params.set("document_id", documentId);
    if (hubOnly) params.set("hub_only", "true");
    return backendFetch<BackendGraph>(`/api/v1/graph/explore?${params.toString()}`);
  },

  documentEntitySummary: (documentId: string) =>
    backendFetch<{
      document_id: string;
      total_entities: number;
      types: Array<{ label: string; count: number }>;
    }>(`/api/v1/graph/documents/${encodeURIComponent(documentId)}/summary`),

  documentEntitiesByType: (
    documentId: string,
    entityType: string,
    limit = GRAPH_TYPE_PAGE_LIMIT,
    offset = 0
  ) =>
    backendFetch<{
      document_id: string;
      entity_label: string;
      offset: number;
      limit: number;
      total: number;
      has_more: boolean;
      nodes: BackendGraphNode[];
      edges: Array<{ source: string; target: string; type: string }>;
    }>(
      `/api/v1/graph/documents/${encodeURIComponent(documentId)}/entities?${new URLSearchParams({
        entity_type: entityType,
        limit: String(limit),
        offset: String(offset),
      }).toString()}`
    ),

  getNodeNeighbors: (nodeId: string, limit = 40) =>
    backendFetch<BackendGraph>(
      `/api/v1/graph/nodes/${encodeURIComponent(nodeId)}/neighbors?limit=${limit}`
    ),

  reconcileDuplicateEntities: () =>
    backendFetch<{ merged_group_count: number; groups: unknown[] }>(
      "/api/v1/graph/dedupe/entities",
      { method: "POST" }
    ),

  graphSearch: (q: string, limit = 20) =>
    backendFetch<{ query: string; results: BackendGraphNode[]; count: number }>(
      `/api/v1/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`
    ),

  browseEntities: (
    entityType: string,
    q?: string,
    limit = 100,
    offset = 0
  ) => {
    const params = new URLSearchParams({
      entity_type: entityType,
      limit: String(limit),
      offset: String(offset),
    });
    if (q?.trim()) params.set("q", q.trim());
    return backendFetch<{
      items: Array<{ id: string; label: string; type: string }>;
      total: number;
      limit: number;
      offset: number;
      entity_label: string;
      has_more: boolean;
    }>(`/api/v1/graph/entities?${params.toString()}`);
  },

  experimentsByMaterial: (material: string, regimeType?: string) => {
    const params = new URLSearchParams({ material });
    if (regimeType) params.set("regime_type", regimeType);
    return backendFetch<{ experiments: BackendExperiment[]; count: number }>(
      `/api/v1/graph/experiments/by-material?${params}`
    );
  },

  getExperiment: (experimentId: string) =>
    backendFetch<BackendExperimentDetails>(`/api/v1/graph/experiments/${experimentId}`),

  getProperty: (propertyId: string) =>
    backendFetch<BackendPropertyDetails>(
      `/api/v1/graph/properties/${encodeURIComponent(propertyId)}`
    ),

  dataGaps: () =>
    backendFetch<{ gaps: BackendGap[]; count: number }>(
      "/api/v1/graph/analytics/gaps"
    ),

  contradictions: () =>
    backendFetch<{ contradictions: BackendContradiction[]; count: number }>(
      "/api/v1/graph/analytics/contradictions"
    ),

  structuredQuery: (filters: StructuredFiltersPayload) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v != null && v !== "") params.set(k, String(v));
    });
    return backendFetch<BackendStructuredResult>(
      `/api/v1/graph/query?${params.toString()}`
    );
  },

  exportJsonLd: () => backendFetch<Record<string, unknown>>("/api/v1/graph/export/json-ld"),

  ragSearch: (text: string, documentId?: string, structured?: StructuredFiltersPayload) =>
    backendFetch<BackendRagResult>("/api/v1/search/json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        ...(documentId ? { document_id: documentId } : {}),
        ...(structured && Object.keys(structured).length
          ? { structured }
          : {}),
      }),
    }),

  ingestFile: async (file: File): Promise<IngestTask> => {
    const form = new FormData();
    form.append("file", file);
    return backendFetch<IngestTask>("/api/v1/ingest/file", {
      method: "POST",
      body: form,
    });
  },

  ingestUrl: (url: string) =>
    backendFetch<IngestTask>("/api/v1/ingest/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, use_playwright: false }),
    }),

  ingestStatus: (taskId: string) =>
    backendFetch<IngestTaskStatus>(`/api/v1/ingest/status/${taskId}`),

  ingestActive: () =>
    backendFetch<{ active: boolean; count: number; message: string }>(
      "/api/v1/ingest/active"
    ),

  listDocuments: () =>
    backendFetch<Array<{ id: string; title: string; file_path?: string; chunks_count?: number }>>(
      "/api/v1/ingest/documents"
    ),

  getDocument: (documentId: string) =>
    backendFetch<BackendDocument>(`/api/v1/ingest/documents/${documentId}`),

  deleteDocument: (documentId: string) =>
    backendFetch<{ status: string; document_id: string }>(
      `/api/v1/ingest/documents/${encodeURIComponent(documentId)}`,
      { method: "DELETE" }
    ),
};

export { BACKEND_URL };
