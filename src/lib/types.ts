export type EntityType =
  | "article"
  | "experiment"
  | "material"
  | "property"
  | "mode"
  | "setup"
  | "team"
  | "conclusion"
  | "topic"
  | "equipment"
  | "process"
  | "facility"
  | "expert"
  | "figures";

export interface BaseEntity {
  id: string;
  type: EntityType;
  name: string;
  description?: string;
  tags?: string[];
}

export interface Article extends BaseEntity {
  type: "article";
  source: "internal" | "external";
  format: "pdf" | "word" | "web";
  authors: string[];
  publishedAt: string;
  textLayer: string;
  url?: string;
}

export interface Experiment extends BaseEntity {
  type: "experiment";
  code: string;
  startedAt: string;
  completedAt?: string;
  status: "completed" | "ongoing" | "planned";
  materialId: string;
  modeId: string;
  setupId: string;
  teamId: string;
  propertyIds: string[];
  conclusionId?: string;
  articleIds: string[];
  measurements: Measurement[];
}

export interface Measurement {
  propertyId: string;
  before?: number;
  after?: number;
  unit: string;
  changePercent?: number;
  notes?: string;
}

export interface Material extends BaseEntity {
  type: "material";
  composition: string;
  category: string;
  components?: string[];
}

export interface Property extends BaseEntity {
  type: "property";
  unit: string;
  higherIsBetter: boolean;
  canonicalName?: string;
  measurements?: PropertyMeasurement[];
}

export interface PropertyMeasurement {
  value: string;
  unit: string;
  source: "experiment" | "material";
  experimentName?: string;
  materialName?: string;
  documentTitle?: string;
  sourceText?: string;
}

export interface Mode extends BaseEntity {
  type: "mode";
  category: string;
}

export interface Setup extends BaseEntity {
  type: "setup";
  equipmentIds: string[];
  location: string;
}

export interface Equipment extends BaseEntity {
  type: "equipment";
  model: string;
  labId: string;
}

export interface Team extends BaseEntity {
  type: "team";
  lab: string;
  lead: string;
  members: string[];
}

export interface Facility extends BaseEntity {
  type: "facility";
  country?: string;
  facilityType?: string;
}

export interface Conclusion extends BaseEntity {
  type: "conclusion";
  summary: string;
  confidence: "high" | "medium" | "low";
  effect: "positive" | "negative" | "neutral" | "mixed";
}

export interface Topic extends BaseEntity {
  type: "topic";
}

export interface DocumentFigure {
  id: string;
  caption?: string;
  page_number?: number;
  image_type?: string;
  storage_key?: string;
}

export interface Figures extends BaseEntity {
  type: "figures";
  documentId: string;
  imageCount: number;
  typeSummary?: string;
  items: DocumentFigure[];
}

export type Entity =
  | Article
  | Experiment
  | Material
  | Property
  | Mode
  | Setup
  | Equipment
  | Team
  | Facility
  | Conclusion
  | Topic
  | Figures;

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation:
    | "describes"
    | "uses_material"
    | "under_mode"
    | "measures"
    | "uses_setup"
    | "conducted_by"
    | "concludes"
    | "tagged"
    | "references"
    | "employs"
    | "processed_in"
    | "has_figures";
}

export interface GraphNode {
  id: string;
  type: EntityType;
  name: string;
  val: number;
  color: string;
  /** Individual materials when this node is a merged blob */
  components?: string[];
  memberIds?: string[];
  /** Team member names when type is team */
  members?: string[];
  country?: string;
  facilityType?: string;
  figures?: DocumentFigure[];
  documentId?: string;
  imageCount?: number;
  typeSummary?: string;
  regimeName?: string;
  regimeDescription?: string;
  experimentStatus?: Experiment["status"];
  conclusionText?: string;
  sampleValue?: string;
  sampleUnit?: string;
  /** Virtual capsule node grouping entities of one type under a document hub. */
  isTypeCluster?: boolean;
  typeClusterCount?: number;
  hubId?: string;
}

export interface SourceExcerpt {
  index: number;
  text: string;
  documentId: string;
  title?: string | null;
}

export interface RetrievalScope {
  mode: "full_corpus" | "explicit_document" | "structured_filters" | "structured_fallback";
  filterDocumentIds?: string[];
  filterDocumentTitles?: string[];
  filtersApplied?: Record<string, unknown>;
  graphMatchCount?: number;
}

export interface StructuredExperimentRow {
  experiment_id?: string;
  material?: string;
  process?: string;
  regime?: string;
  document_id?: string;
  document_title?: string;
  year?: number;
}

export interface SearchResult {
  query: string;
  parsed: ParsedQuery;
  experiments: ExperimentResult[];
  relatedEntities: Entity[];
  graph: { nodes: GraphNode[]; links: GraphEdge[] };
  gaps: DataGap[];
  narrative: string;
  sources: SourceExcerpt[];
  confidence?: number;
  needsDisambiguation?: boolean;
  documentCandidates?: Array<{ documentId: string; title?: string | null; score?: number }>;
  retrievalScope?: RetrievalScope;
  /** Graph node IDs from text search on the knowledge graph. */
  graphMatchIds?: string[];
  /** Rows from structured graph query (filters / experiments). */
  structuredExperiments?: StructuredExperimentRow[];
}

export interface ParsedQuery {
  material?: string;
  mode?: string;
  property?: string;
  team?: string;
  geography?: string;
  keywords: string[];
}

export interface StructuredFilters {
  material?: string;
  materialClass?: string;
  process?: string;
  geography?: string;
  yearFrom?: number;
  yearTo?: number;
  propertyName?: string;
  valueMin?: number;
  valueMax?: number;
}

export interface ExperimentResult {
  experiment: Experiment;
  material?: Material;
  mode?: Mode;
  properties: Property[];
  team?: Team;
  conclusion?: Conclusion;
  relevance: number;
  effectSummary: string;
}

export interface DataGap {
  material: string;
  mode: string;
  property: string;
  priority: "high" | "medium" | "low";
  reason: string;
}
