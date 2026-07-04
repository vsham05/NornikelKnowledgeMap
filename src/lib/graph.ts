import type { EntityType } from "./types";
import { translate, type Locale } from "./i18n/translations";

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
  process: "#38bdf8",
  facility: "#c084fc",
  expert: "#fdba74",
  figures: "#a855f7",
};

export function getEntityColor(type: EntityType): string {
  return ENTITY_COLORS[type];
}

export function getEntityLabel(type: EntityType, locale?: Locale): string {
  if (locale) {
    return translate(locale, `entity.${type}`);
  }
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
    process: "Process",
    facility: "Facility",
    expert: "Expert",
    figures: "Figures",
  };
  return labels[type];
}

/** Visual radius multiplier — keep in sync with GraphView nodeRadius. */
export const NODE_RADIUS_SCALE = 5;

/** Minimum gap between node circles (~1 cm at typical screen DPI when zoomed to fit). */
export const NODE_GAP_PX = 38;

/** Layout val for expanded entity nodes — keep in sync with GraphView ENTITY_NODE_VAL. */
export const LAYOUT_ENTITY_VAL = 2.2;

export function graphNodeRadius(val: number = 4): number {
  return Math.sqrt(val) * NODE_RADIUS_SCALE;
}

/** d3-force collide radius (half-gap + node radius). */
export function graphCollisionRadius(val: number = 4): number {
  return graphNodeRadius(val) + NODE_GAP_PX / 2;
}

/** Minimum center-to-center distance for two nodes with the same val. */
export function minNodeCenterDistance(val: number = 4): number {
  return 2 * graphNodeRadius(val) + NODE_GAP_PX;
}

/** Ring radius so `count` nodes sit at least minNodeCenterDistance apart on the arc. */
export function ringRadiusForCount(count: number, val: number = 4): number {
  if (count <= 1) return minNodeCenterDistance(val) * 1.2;
  return Math.max(
    minNodeCenterDistance(val) * 1.2,
    (count * minNodeCenterDistance(val)) / (2 * Math.PI)
  );
}
