import type { BackendDocument, BackendExperimentDetails, BackendPropertyDetails } from "@/lib/api/backend";
import type {
  Article,
  Entity,
  Experiment,
  Figures,
  GraphNode,
  Material,
  Measurement,
  Property,
  PropertyMeasurement,
  Team,
  Facility,
} from "@/lib/types";
import { parseMaterialComponents } from "@/lib/materialComponents";

function inferFormat(filePath: string): Article["format"] {
  const lower = filePath.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) return "web";
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".docx") || lower.endsWith(".doc")) return "word";
  return "web";
}

function parseExperimentStatus(
  status: string | undefined
): Experiment["status"] {
  const raw = (status ?? "completed").toLowerCase();
  if (raw === "ongoing" || raw === "planned") return raw;
  return "completed";
}

function graphNodeToExperiment(node: GraphNode): Experiment {
  const summary =
    node.conclusionText?.trim() ||
    node.regimeDescription?.trim() ||
    node.name;
  return {
    id: node.id,
    type: "experiment",
    name: node.regimeName?.trim() || node.name,
    code: node.id.slice(0, 12),
    startedAt: "—",
    status: node.experimentStatus ?? "completed",
    materialId: "",
    modeId: "",
    setupId: "",
    teamId: "",
    propertyIds: [],
    articleIds: [],
    measurements: [],
    description: summary,
  };
}

export function experimentDetailsToEntity(
  node: GraphNode,
  details: BackendExperimentDetails
): Experiment {
  const id = details.id ?? node.id;
  const rawConclusions = details.conclusions;
  const conclusionText = Array.isArray(rawConclusions)
    ? rawConclusions.map(String).filter(Boolean).join("; ")
    : typeof rawConclusions === "string"
      ? rawConclusions
      : "";

  const measurements: Measurement[] = (details.measured_properties ?? [])
    .filter((item) => item?.name)
    .map((item) => {
      const numeric =
        typeof item.value === "number"
          ? item.value
          : Number.parseFloat(String(item.value ?? ""));
      return {
        propertyId: String(item.name),
        after: Number.isFinite(numeric) ? numeric : undefined,
        unit: item.unit ? String(item.unit) : "",
      };
    });

  const description =
    conclusionText ||
    details.regime_description ||
    node.regimeDescription ||
    node.name;

  return {
    id,
    type: "experiment",
    name:
      details.regime_name?.trim() ||
      node.regimeName?.trim() ||
      node.name ||
      id.slice(0, 12),
    code: id.slice(0, 12),
    startedAt: details.created_at?.slice(0, 10) || "—",
    status: parseExperimentStatus(details.status ?? node.experimentStatus),
    materialId: "",
    modeId: "",
    setupId: "",
    teamId: "",
    propertyIds: measurements.map((m) => m.propertyId),
    articleIds: [],
    measurements,
    description,
  };
}

export function propertyDetailsToEntity(
  node: GraphNode,
  details: BackendPropertyDetails
): Property {
  const canonical =
    details.canonical_name ||
    (node.id.startsWith("prop:") ? node.id.slice(5) : node.id);
  const measurements: PropertyMeasurement[] = [];
  const seen = new Set<string>();
  for (const item of details.measurements ?? []) {
    if (item?.value == null || String(item.value).trim() === "") continue;
    const key = `${item.material_name ?? ""}|${item.experiment_name ?? ""}|${item.value}`;
    if (seen.has(key)) continue;
    seen.add(key);
    measurements.push({
      value: String(item.value),
      unit: item.unit ? String(item.unit) : "",
      source: item.source === "material" ? "material" : "experiment",
      experimentName: item.experiment_name ? String(item.experiment_name) : undefined,
      materialName: item.material_name ? String(item.material_name) : undefined,
      documentTitle: item.document_title ? String(item.document_title) : undefined,
      sourceText: item.source_text ? String(item.source_text) : undefined,
    });
  }

  return {
    id: node.id,
    type: "property",
    name: details.display_label?.trim() || node.name,
    canonicalName: canonical,
    unit: details.unit ? String(details.unit) : measurements[0]?.unit ?? "",
    higherIsBetter: true,
    measurements,
  };
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

  if (node.type === "figures") {
    return {
      id: node.id,
      type: "figures",
      name: node.name,
      documentId: node.documentId ?? node.id.replace(/:figures$/, ""),
      imageCount: node.imageCount ?? node.figures?.length ?? 0,
      typeSummary: node.typeSummary,
      items: node.figures ?? [],
    } satisfies Figures;
  }

  if (node.type === "experiment") {
    return graphNodeToExperiment(node);
  }

  if (node.type === "property") {
    return {
      id: node.id,
      type: "property",
      name: node.name,
      unit: node.sampleUnit ?? "",
      higherIsBetter: true,
      measurements: node.sampleValue
        ? [{ value: node.sampleValue, unit: node.sampleUnit ?? "", source: "experiment" }]
        : [],
    } satisfies Property;
  }

  return {
    id: node.id,
    type: node.type,
    name: node.name,
    description: node.regimeDescription,
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
