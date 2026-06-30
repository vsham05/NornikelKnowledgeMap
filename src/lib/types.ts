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
  | "equipment";

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
}

export interface Property extends BaseEntity {
  type: "property";
  unit: string;
  higherIsBetter: boolean;
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

export interface Conclusion extends BaseEntity {
  type: "conclusion";
  summary: string;
  confidence: "high" | "medium" | "low";
  effect: "positive" | "negative" | "neutral" | "mixed";
}

export interface Topic extends BaseEntity {
  type: "topic";
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
  | Conclusion
  | Topic;

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
    | "employs";
}

export interface GraphNode {
  id: string;
  type: EntityType;
  name: string;
  val: number;
  color: string;
}

export interface SourceExcerpt {
  index: number;
  text: string;
  documentId: string;
  title?: string | null;
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
}

export interface ParsedQuery {
  material?: string;
  mode?: string;
  property?: string;
  team?: string;
  keywords: string[];
}

export interface ExperimentResult {
  experiment: Experiment;
  material: Material;
  mode: Mode;
  properties: Property[];
  team: Team;
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
