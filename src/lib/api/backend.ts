const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

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
  try {
    const res = await fetch(`${BACKEND_URL}/health`, {
      signal: AbortSignal.timeout(3000),
    });
    return res.ok;
  } catch {
    return false;
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
  result?: Record<string, unknown>;
  error?: string | null;
}

export const backendApi = {
  health: () => backendFetch<{ status: string }>("/health"),

  graphStats: () => backendFetch<BackendStats>("/api/v1/graph/stats"),

  enrichAllDocuments: () =>
    backendFetch<{ processed: number; enriched: number }>("/api/v1/graph/enrich-all", {
      method: "POST",
    }),

  exploreGraph: (limit = 200) =>
    backendFetch<BackendGraph>(`/api/v1/graph/explore?limit=${limit}`),

  graphSearch: (q: string, limit = 20) =>
    backendFetch<{ query: string; results: BackendGraphNode[]; count: number }>(
      `/api/v1/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`
    ),

  experimentsByMaterial: (material: string, regimeType?: string) => {
    const params = new URLSearchParams({ material });
    if (regimeType) params.set("regime_type", regimeType);
    return backendFetch<{ experiments: BackendExperiment[]; count: number }>(
      `/api/v1/graph/experiments/by-material?${params}`
    );
  },

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

  listDocuments: () =>
    backendFetch<Array<{ id: string; title: string; file_path?: string; chunks_count?: number }>>(
      "/api/v1/ingest/documents"
    ),

  getDocument: (documentId: string) =>
    backendFetch<BackendDocument>(`/api/v1/ingest/documents/${documentId}`),
};

export { BACKEND_URL };
