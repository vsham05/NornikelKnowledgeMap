import type { EntityType } from "./types";

const ENTITY_COLORS: Record<EntityType, string> = {
  article: "#60a5fa",
  experiment: "#34d399",
  material: "#f472b6",
  property: "#fbbf24",
  mode: "#a78bfa",
  setup: "#94a3b8",
  team: "#fb923c",
  conclusion: "#2dd4bf",
  topic: "#64748b",
  equipment: "#78716c",
};

export function getEntityColor(type: EntityType): string {
  return ENTITY_COLORS[type];
}

export function getEntityLabel(type: EntityType): string {
  const labels: Record<EntityType, string> = {
    article: "Document",
    experiment: "Experiment",
    material: "Material",
    property: "Property",
    mode: "Mode",
    setup: "Setup",
    team: "Team",
    conclusion: "Conclusion",
    topic: "Topic",
    equipment: "Equipment",
  };
  return labels[type];
}
