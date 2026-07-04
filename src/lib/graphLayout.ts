import type { EntityType, GraphEdge, GraphNode } from "@/lib/types";
import { isTypeClusterNode } from "@/lib/graphHierarchy";
import {
  graphCollisionRadius,
  graphNodeRadius,
  minNodeCenterDistance,
  NODE_GAP_PX,
  ringRadiusForCount,
  LAYOUT_ENTITY_VAL,
} from "@/lib/graph";
import { deduplicateGraphEntities } from "@/lib/graphDedup";

export type LayoutNode = GraphNode & {
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
  clusterId?: string;
  clusterCx?: number;
  clusterCy?: number;
  clusterType?: EntityType;
  clusterSize?: number;
  layoutRole?: "ring" | "grid" | "hub";
  hubId?: string;
  collapsedChildCount?: number;
  isCollapsedHub?: boolean;
};

type ProcessCluster = {
  id: string;
  process: GraphNode | null;
  satellites: GraphNode[];
};

/** Preferred angular order for type sectors around a document hub (Bloom-style). */
export const CLUSTER_TYPE_ORDER: EntityType[] = [
  "process",
  "material",
  "experiment",
  "property",
  "equipment",
  "facility",
  "expert",
  "team",
  "figures",
  "mode",
  "setup",
  "conclusion",
  "topic",
];

/** Fixed angular slots for inner type grids (reference-map style). */
const INNER_TYPE_SLOTS: Array<{ type: EntityType; angleDeg: number }> = [
  { type: "process", angleDeg: -90 },
  { type: "team", angleDeg: -138 },
  { type: "experiment", angleDeg: -38 },
  { type: "property", angleDeg: 32 },
  { type: "equipment", angleDeg: 78 },
  { type: "facility", angleDeg: 128 },
  { type: "expert", angleDeg: 168 },
  { type: "figures", angleDeg: -68 },
  { type: "mode", angleDeg: 8 },
  { type: "setup", angleDeg: 48 },
  { type: "conclusion", angleDeg: 108 },
  { type: "topic", angleDeg: -168 },
  { type: "material", angleDeg: 52 },
];

/** Distance from document hub to compressed type capsules (shared with expanded layout). */
const CAPSULE_RING_R = 145;
/** Clear band between capsule edge and first expanded entity (~1 cm base + 2 cm extra). */
const CAPSULE_TO_GRID_GAP = 88 + 2 * NODE_GAP_PX;
/** Typical visual radius of a type summary capsule (val ~10–18 + halo). */
const TYPE_CAPSULE_VAL = 12;

function typeCapsuleOuterRadius(): number {
  return graphNodeRadius(TYPE_CAPSULE_VAL) + 8;
}

/** Inner edge of an expanded grid — must sit outside the capsule on its spoke. */
function minGridInnerRadius(): number {
  return CAPSULE_RING_R + typeCapsuleOuterRadius() + CAPSULE_TO_GRID_GAP;
}

/** Outermost spoke distance for a grid center placed along a capsule spoke. */
function axisGridCenterRadius(count: number, step: number): number {
  const fp = gridFootprint(count, step);
  return minGridInnerRadius() + fp.halfH + NODE_GAP_PX * 0.5;
}

/** Furthest hub distance for an axis-aligned grid on a spoke. */
function axisGridHubExtent(count: number, step: number, angleDeg: number): number {
  const fp = gridFootprint(count, step);
  const centerR = axisGridCenterRadius(count, step);
  const { x: cx, y: cy } = spokePoint({ x: 0, y: 0 }, angleDeg, centerR);
  const corners: Array<[number, number]> = [
    [cx - fp.halfW, cy - fp.halfH],
    [cx + fp.halfW, cy - fp.halfH],
    [cx - fp.halfW, cy + fp.halfH],
    [cx + fp.halfW, cy + fp.halfH],
  ];
  return Math.max(...corners.map(([x, y]) => Math.hypot(x, y)));
}

type ClusterBox = {
  clusterId: string;
  cx: number;
  cy: number;
  halfW: number;
  halfH: number;
};

function clusterBoxFromNodes(nodes: LayoutNode[]): ClusterBox | null {
  if (nodes.length === 0) return null;
  const clusterId = nodes[0].clusterId ?? nodes[0].id;
  const xs = nodes.map((n) => n.x ?? 0);
  const ys = nodes.map((n) => n.y ?? 0);
  const pad = NODE_GAP_PX * 0.65;
  return {
    clusterId,
    cx: (Math.min(...xs) + Math.max(...xs)) / 2,
    cy: (Math.min(...ys) + Math.max(...ys)) / 2,
    halfW: (Math.max(...xs) - Math.min(...xs)) / 2 + pad,
    halfH: (Math.max(...ys) - Math.min(...ys)) / 2 + pad,
  };
}

function clusterBoxesOverlap(a: ClusterBox, b: ClusterBox, gap = NODE_GAP_PX): boolean {
  return (
    Math.abs(a.cx - b.cx) < a.halfW + b.halfW + gap &&
    Math.abs(a.cy - b.cy) < a.halfH + b.halfH + gap
  );
}

function translateClusterNodes(nodes: LayoutNode[], dx: number, dy: number): void {
  for (const node of nodes) {
    node.x = (node.x ?? 0) + dx;
    node.y = (node.y ?? 0) + dy;
    node.fx = node.x;
    node.fy = node.y;
    if (node.clusterCx != null) node.clusterCx += dx;
    if (node.clusterCy != null) node.clusterCy += dy;
  }
}

function slotAngleDeg(type: EntityType): number {
  const slot = INNER_TYPE_SLOTS.find((s) => s.type === type);
  return slot?.angleDeg ?? -90;
}

function spokePoint(
  hubPos: { x: number; y: number },
  angleDeg: number,
  radius: number
): { x: number; y: number } {
  const angle = (angleDeg * Math.PI) / 180;
  return {
    x: hubPos.x + Math.cos(angle) * radius,
    y: hubPos.y + Math.sin(angle) * radius,
  };
}

function pinNode(
  node: GraphNode,
  x: number,
  y: number,
  hubId: string,
  extra: Partial<LayoutNode> = {}
): LayoutNode {
  return { ...node, x, y, fx: x, fy: y, hubId, ...extra };
}

function layoutCompactGrid(
  cx: number,
  cy: number,
  nodes: GraphNode[],
  hubId: string,
  type: EntityType,
  cellStep?: number
): LayoutNode[] {
  if (nodes.length === 0) return [];
  const step = cellStep ?? minNodeCenterDistance(LAYOUT_ENTITY_VAL);
  if (nodes.length === 1) {
    return [
      pinNode(nodes[0], cx, cy, hubId, {
        clusterId: `${hubId}:${type}`,
        clusterType: type,
        clusterSize: 1,
        layoutRole: "grid",
        val: LAYOUT_ENTITY_VAL,
      }),
    ];
  }

  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length * 0.82)));
  const rows = Math.ceil(nodes.length / cols);
  const clusterId = `${hubId}:${type}`;

  return nodes.map((node, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = cx + (col - (cols - 1) / 2) * step;
    const y = cy + (row - (rows - 1) / 2) * step;
    return pinNode(node, x, y, hubId, {
      clusterId,
      clusterCx: cx,
      clusterCy: cy,
      clusterType: type,
      clusterSize: nodes.length,
      layoutRole: "grid",
      val: LAYOUT_ENTITY_VAL,
    });
  });
}

function gridFootprint(count: number, step: number): { cols: number; rows: number; halfW: number; halfH: number } {
  const cols = Math.max(1, Math.ceil(Math.sqrt(count * 0.82)));
  const rows = Math.ceil(count / cols);
  return {
    cols,
    rows,
    halfW: (Math.max(0, cols - 1) * step) / 2 + step * 0.6,
    halfH: (Math.max(0, rows - 1) * step) / 2 + step * 0.6,
  };
}

/**
 * Estimate how far a hub's content extends from its center (for multi-document spacing).
 */
function estimateHubLayoutRadius(entities: GraphNode[]): number {
  const step = minNodeCenterDistance(LAYOUT_ENTITY_VAL);
  const real = entities.filter((n) => !isTypeClusterNode(n));
  const clusters = entities.filter((n) => isTypeClusterNode(n));

  if (real.length === 0) {
    return CAPSULE_RING_R + step * 2 + clusters.length * 4;
  }

  let maxR = minGridInnerRadius() + step * 2;
  const byType = new Map<EntityType, GraphNode[]>();
  for (const node of real) {
    if (node.type === "material") continue;
    const bucket = byType.get(node.type) ?? [];
    bucket.push(node);
    byType.set(node.type, bucket);
  }

  for (const [type, group] of byType) {
    maxR = Math.max(maxR, axisGridHubExtent(group.length, step, slotAngleDeg(type)));
  }

  const materials = real.filter((n) => n.type === "material");
  if (materials.length > 0) {
    if (materials.length <= 36) {
      maxR = Math.max(maxR, minGridInnerRadius() + step * 2.5);
    } else {
      maxR = Math.max(
        maxR,
        axisGridHubExtent(materials.length, step, slotAngleDeg("material"))
      );
    }
  }

  return maxR;
}

/** Find a non-overlapping center for an axis-aligned grid near its capsule spoke. */
function placeAxisGridCenter(
  hubPos: { x: number; y: number },
  angleDeg: number,
  count: number,
  step: number,
  placed: ClusterBox[]
): { cx: number; cy: number } {
  const fp = gridFootprint(count, step);
  const pad = NODE_GAP_PX * 0.65;
  const halfW = fp.halfW + pad;
  const halfH = fp.halfH + pad;
  const angle = (angleDeg * Math.PI) / 180;
  const radialX = Math.cos(angle);
  const radialY = Math.sin(angle);
  const tangentX = -Math.sin(angle);
  const tangentY = Math.cos(angle);

  let centerR = axisGridCenterRadius(count, step);
  let cx = hubPos.x + radialX * centerR;
  let cy = hubPos.y + radialY * centerR;

  for (let attempt = 0; attempt < 80; attempt++) {
    const probe: ClusterBox = {
      clusterId: "",
      cx,
      cy,
      halfW,
      halfH,
    };
    if (!placed.some((box) => clusterBoxesOverlap(probe, box))) {
      return { cx, cy };
    }
    if (attempt < 40) {
      centerR += step * 0.7;
      cx = hubPos.x + radialX * centerR;
      cy = hubPos.y + radialY * centerR;
    } else {
      const tangSign = attempt % 2 === 0 ? 1 : -1;
      const tOffset = Math.ceil((attempt - 39) / 2) * step * 0.55 * tangSign;
      cx = hubPos.x + radialX * centerR + tangentX * tOffset;
      cy = hubPos.y + radialY * centerR + tangentY * tOffset;
    }
  }

  return { cx, cy };
}

/** Move whole grid clusters apart when their axis-aligned boxes overlap. */
function resolveClusterBoxOverlaps(nodes: LayoutNode[], maxIter = 120): void {
  const byCluster = new Map<string, LayoutNode[]>();
  for (const node of nodes) {
    if (node.layoutRole !== "grid" || !node.clusterId) continue;
    const bucket = byCluster.get(node.clusterId) ?? [];
    bucket.push(node);
    byCluster.set(node.clusterId, bucket);
  }

  const clusterIds = [...byCluster.keys()];
  if (clusterIds.length < 2) return;

  for (let iter = 0; iter < maxIter; iter++) {
    let moved = false;
    const boxes = clusterIds
      .map((id) => clusterBoxFromNodes(byCluster.get(id)!))
      .filter((b): b is ClusterBox => b != null);

    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        if (!clusterBoxesOverlap(a, b)) continue;

        const dx = b.cx - a.cx || 0.001;
        const dy = b.cy - a.cy || 0.001;
        const dist = Math.hypot(dx, dy) || 0.001;
        const overlapX = a.halfW + b.halfW + NODE_GAP_PX - Math.abs(b.cx - a.cx);
        const overlapY = a.halfH + b.halfH + NODE_GAP_PX - Math.abs(b.cy - a.cy);
        const push = Math.max(overlapX, overlapY, 1) * 0.55;
        const ux = dx / dist;
        const uy = dy / dist;

        translateClusterNodes(byCluster.get(a.clusterId)!, -ux * push, -uy * push);
        translateClusterNodes(byCluster.get(b.clusterId)!, ux * push, uy * push);
        moved = true;
      }
    }

    if (!moved) break;
  }
}

/**
 * Expanded entities sit in axis-aligned square grids near their type capsule spoke.
 */
function layoutHubEntitiesRadialMap(
  hubId: string,
  hubPos: { x: number; y: number },
  entities: GraphNode[]
): LayoutNode[] {
  if (entities.length === 0) return [];

  const step = minNodeCenterDistance(LAYOUT_ENTITY_VAL);
  const materials = entities.filter((n) => n.type === "material");
  const byType = new Map<EntityType, GraphNode[]>();
  for (const entity of entities) {
    if (entity.type === "material") continue;
    const bucket = byType.get(entity.type) ?? [];
    bucket.push(entity);
    byType.set(entity.type, bucket);
  }

  const out: LayoutNode[] = [];
  const placed: ClusterBox[] = [];

  const layoutGroup = (group: GraphNode[], type: EntityType, angleDeg: number) => {
    if (group.length === 0) return;
    const { cx, cy } = placeAxisGridCenter(hubPos, angleDeg, group.length, step, placed);
    const laid = layoutCompactGrid(cx, cy, group, hubId, type, step);
    const box = clusterBoxFromNodes(laid);
    if (box) placed.push(box);
    out.push(...laid);
  };

  if (materials.length > 0) {
    const matAngle = slotAngleDeg("material");
    if (materials.length <= 6) {
      const ringR = minGridInnerRadius() + step * 1.2;
      const arcSpan = Math.min(Math.PI * 1.1, (materials.length * step) / Math.max(ringR, step));
      const centerAngle = (matAngle * Math.PI) / 180;
      const startAngle = centerAngle - arcSpan / 2;
      materials.forEach((node, i) => {
        const t = materials.length === 1 ? 0.5 : i / (materials.length - 1);
        const a = startAngle + t * arcSpan;
        const x = hubPos.x + Math.cos(a) * ringR;
        const y = hubPos.y + Math.sin(a) * ringR;
        out.push(
          pinNode(node, x, y, hubId, {
            clusterId: `${hubId}:material`,
            clusterType: "material",
            clusterSize: materials.length,
            layoutRole: "ring",
            val: LAYOUT_ENTITY_VAL,
          })
        );
      });
    } else {
      layoutGroup(materials, "material", matAngle);
    }
  }

  const typeOrder = [
    ...CLUSTER_TYPE_ORDER.filter((t) => byType.has(t)),
    ...[...byType.keys()].filter((t) => !CLUSTER_TYPE_ORDER.includes(t)),
  ];
  typeOrder.sort(
    (a, b) => (byType.get(b)?.length ?? 0) - (byType.get(a)?.length ?? 0)
  );

  for (const type of typeOrder) {
    const group = byType.get(type);
    if (!group) continue;
    layoutGroup(group, type, slotAngleDeg(type));
  }

  resolveClusterBoxOverlaps(out);
  return out;
}

/** Place type summary capsules on fixed slots around the document hub. */
function layoutHubTypeClusters(
  hubId: string,
  hubPos: { x: number; y: number },
  clusters: GraphNode[]
): LayoutNode[] {
  if (clusters.length === 0) return [];

  return clusters.map((node) => {
    const angleDeg = slotAngleDeg(node.type);
    const { x, y } = spokePoint(hubPos, angleDeg, CAPSULE_RING_R);
    return pinNode(node, x, y, hubId, { layoutRole: "grid" });
  });
}

/** Drop hub membership spokes — they create dense beams through the document node. */
export function filterVisualGraphLinks(
  links: GraphEdge[],
  nodeById: Map<string, Pick<GraphNode, "type">>
): GraphEdge[] {
  return links.filter((link) => {
    const [a, b] = linkEndpoints(link);
    const na = nodeById.get(a);
    const nb = nodeById.get(b);
    if (!na || !nb) return false;

    const touchesArticle = na.type === "article" || nb.type === "article";
    if (touchesArticle) {
      if (link.relation === "describes" || link.relation === "references") return false;
      if (isTypeClusterNode({ id: a }) || isTypeClusterNode({ id: b })) return false;
      return false;
    }

    // Entity–entity edges render only in search-focus (Q&A) mode — see GraphView graphLinks.
    return true;
  });
}

function linkEndpoints(link: GraphEdge): [string, string] {
  return [String(link.source), String(link.target)];
}

function buildAdjacency(links: GraphEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  for (const link of links) {
    const [a, b] = linkEndpoints(link);
    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a)!.add(b);
    adj.get(b)!.add(a);
  }
  return adj;
}

function reachableFromDocuments(
  nodes: GraphNode[],
  adj: Map<string, Set<string>>,
  maxDepth = 4
): Set<string> {
  const docs = nodes.filter((n) => n.type === "article");
  const docIds = new Set(docs.map((d) => d.id));
  const keep = new Set<string>();

  for (const node of nodes) {
    if (node.type === "article") {
      keep.add(node.id);
      continue;
    }
    const hub = node.hubId ?? node.documentId;
    if (hub && docIds.has(hub)) {
      keep.add(node.id);
    }
  }

  for (const doc of docs) {
    const queue: Array<{ id: string; depth: number }> = [{ id: doc.id, depth: 0 }];
    const seen = new Set<string>();
    while (queue.length) {
      const { id, depth } = queue.shift()!;
      if (seen.has(id)) continue;
      seen.add(id);
      keep.add(id);
      if (depth >= maxDepth) continue;
      for (const nb of adj.get(id) ?? []) {
        if (!seen.has(nb)) queue.push({ id: nb, depth: depth + 1 });
      }
    }
  }
  return keep;
}

function nearestDocument(
  nodeId: string,
  docs: GraphNode[],
  adj: Map<string, Set<string>>
): string | null {
  if (!docs.length) return null;
  const docIds = new Set(docs.map((d) => d.id));
  if (docIds.has(nodeId)) return nodeId;

  const queue = [nodeId];
  const seen = new Set<string>([nodeId]);
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nb of adj.get(cur) ?? []) {
      if (docIds.has(nb)) return nb;
      if (!seen.has(nb)) {
        seen.add(nb);
        queue.push(nb);
      }
    }
  }
  return docs[0]?.id ?? null;
}

function buildMaterialProcessMap(
  nodes: GraphNode[],
  links: GraphEdge[]
): Map<string, string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out = new Map<string, string>();

  for (const link of links) {
    if (link.relation !== "processed_in") continue;
    const [source, target] = linkEndpoints(link);
    const src = byId.get(source);
    const tgt = byId.get(target);
    if (src?.type === "material" && tgt?.type === "process") {
      out.set(source, target);
    }
  }
  return out;
}

function pin(
  node: GraphNode,
  x: number,
  y: number,
  hubId: string,
  clusterId?: string
): LayoutNode {
  return { ...node, x, y, fx: x, fy: y, hubId, clusterId: clusterId ?? hubId };
}

function nodeVal(node: GraphNode, fallback = 5): number {
  return node.val ?? fallback;
}

function processClusterFootprint(cluster: ProcessCluster, val = 7): number {
  const procR = graphNodeRadius(val);
  const n = cluster.satellites.length;
  if (!cluster.process && n === 0) return procR;
  if (!cluster.process && n === 1) {
    return graphNodeRadius(nodeVal(cluster.satellites[0], val));
  }
  if (n === 0) return procR + NODE_GAP_PX / 2;
  if (n === 1) {
    return procR + minNodeCenterDistance(val) + graphNodeRadius(nodeVal(cluster.satellites[0], val));
  }
  const ringR = Math.max(minNodeCenterDistance(val), ringRadiusForCount(n, val));
  return (cluster.process ? procR : 0) + ringR + graphNodeRadius(val);
}

function gridGroupFootprint(nodes: GraphNode[], fallbackVal = 5): number {
  if (nodes.length === 0) return minNodeCenterDistance(fallbackVal);
  if (nodes.length === 1) return graphNodeRadius(nodeVal(nodes[0], fallbackVal));

  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  const rows = Math.ceil(nodes.length / cols);
  const step = Math.max(
    ...nodes.map((n) => minNodeCenterDistance(nodeVal(n, fallbackVal)))
  );
  const maxR = Math.max(
    ...nodes.map((n) => graphNodeRadius(nodeVal(n, fallbackVal)))
  );
  const halfW = ((cols - 1) * step) / 2 + maxR;
  const halfH = ((rows - 1) * step) / 2 + maxR;
  return Math.hypot(halfW, halfH) + NODE_GAP_PX / 2;
}

function orbitRadiusForFootprints(footprints: number[], scale = 1): number {
  const n = footprints.length;
  if (n === 0) return minNodeCenterDistance(7);
  if (n === 1) return (footprints[0] + minNodeCenterDistance(9) * 0.65) * scale;

  let r = 0;
  for (let i = 0; i < n; i++) {
    const chord = footprints[i] + footprints[(i + 1) % n] + NODE_GAP_PX * 0.85;
    r = Math.max(r, chord / (2 * Math.sin(Math.PI / n)));
  }
  const maxFp = Math.max(...footprints);
  return Math.max(r, maxFp + minNodeCenterDistance(9) * 0.45) * scale;
}

function placeOnRing(
  cx: number,
  cy: number,
  nodes: GraphNode[],
  hubId: string,
  clusterId: string,
  val: number,
  out: LayoutNode[]
): void {
  const n = nodes.length;
  if (n === 1) {
    out.push(pin(nodes[0], cx, cy, hubId, clusterId));
    return;
  }
  const ringR = Math.max(minNodeCenterDistance(val), ringRadiusForCount(n, val));
  nodes.forEach((node, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    out.push(
      pin(node, cx + Math.cos(a) * ringR, cy + Math.sin(a) * ringR, hubId, clusterId)
    );
  });
}

function layoutProcessCluster(
  cx: number,
  cy: number,
  cluster: ProcessCluster,
  outwardAngle: number,
  hubId: string,
  out: LayoutNode[]
): void {
  const gap = minNodeCenterDistance(8) * 0.85;
  const satellites = cluster.satellites;

  if (!cluster.process) {
    placeOnRing(cx, cy, satellites, hubId, cluster.id, 7, out);
    return;
  }

  out.push(pin(cluster.process, cx, cy, hubId, cluster.id));

  if (satellites.length === 0) return;

  if (satellites.length === 1) {
    out.push(
      pin(
        satellites[0],
        cx + Math.cos(outwardAngle) * gap,
        cy + Math.sin(outwardAngle) * gap,
        hubId,
        cluster.id
      )
    );
    return;
  }

  const ringR = Math.max(gap, ringRadiusForCount(satellites.length, 7));
  satellites.forEach((node, i) => {
    const a = outwardAngle + (i / satellites.length) * Math.PI * 2;
    out.push(
      pin(
        node,
        cx + Math.cos(a) * ringR,
        cy + Math.sin(a) * ringR,
        hubId,
        cluster.id
      )
    );
  });
}

function layoutTightGroup(
  cx: number,
  cy: number,
  nodes: GraphNode[],
  hubId: string,
  clusterId: string,
  fallbackVal: number,
  out: LayoutNode[]
): void {
  if (nodes.length === 0) return;
  if (nodes.length === 1) {
    out.push(pin(nodes[0], cx, cy, hubId, clusterId));
    return;
  }

  const step = Math.max(
    ...nodes.map((n) => minNodeCenterDistance(nodeVal(n, fallbackVal)))
  );
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  const rows = Math.ceil(nodes.length / cols);

  nodes.forEach((node, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = cx + (col - (cols - 1) / 2) * step;
    const y = cy + (row - (rows - 1) / 2) * step;
    out.push(pin(node, x, y, hubId, clusterId));
  });
}

function resolveCrossClusterOverlaps(nodes: LayoutNode[], maxIter = 120): void {
  for (let iter = 0; iter < maxIter; iter++) {
    let moved = false;

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        if (a.type === "article" || b.type === "article") continue;
        if (a.clusterId && a.clusterId === b.clusterId) continue;

        const ax = a.x ?? 0;
        const ay = a.y ?? 0;
        const bx = b.x ?? 0;
        const by = b.y ?? 0;
        const dx = bx - ax;
        const dy = by - ay;
        const dist = Math.hypot(dx, dy) || 0.001;
        const minDist =
          graphCollisionRadius(nodeVal(a)) + graphCollisionRadius(nodeVal(b));

        if (dist >= minDist) continue;

        const push = (minDist - dist) / 2 + 0.5;
        const ux = dx / dist;
        const uy = dy / dist;

        a.x = ax - ux * push;
        a.y = ay - uy * push;
        a.fx = a.x;
        a.fy = a.y;
        b.x = bx + ux * push;
        b.y = by + uy * push;
        b.fx = b.x;
        b.fy = b.y;
        moved = true;
      }
    }

    if (!moved) break;
  }
}

function layoutHub(
  hubId: string,
  center: { x: number; y: number },
  group: GraphNode[],
  materialToProcess: Map<string, string>,
  out: LayoutNode[]
): number {
  const doc = group.find((n) => n.id === hubId);
  const processes = group.filter((n) => n.type === "process");
  const materials = group.filter((n) => n.type === "material");
  const others = group.filter(
    (n) => n.id !== hubId && n.type !== "process" && n.type !== "material"
  );

  const hubNodes: LayoutNode[] = [];

  if (doc) {
    hubNodes.push(pin(doc, center.x, center.y, hubId));
  }

  const materialsByProcess = new Map<string, GraphNode[]>();
  const unlinkedMaterials: GraphNode[] = [];
  for (const mat of materials) {
    const procId = materialToProcess.get(mat.id);
    if (procId) {
      if (!materialsByProcess.has(procId)) materialsByProcess.set(procId, []);
      materialsByProcess.get(procId)!.push(mat);
    } else {
      unlinkedMaterials.push(mat);
    }
  }

  const processClusters: ProcessCluster[] = processes.map((proc) => ({
    id: proc.id,
    process: proc,
    satellites: materialsByProcess.get(proc.id) ?? [],
  }));

  if (unlinkedMaterials.length > 0) {
    processClusters.push({
      id: `${hubId}:materials`,
      process: null,
      satellites: unlinkedMaterials,
    });
  }

  const people = others.filter((n) => n.type === "expert" || n.type === "team");
  const figureBlobs = others.filter((n) => n.type === "figures");
  const equipment = others.filter(
    (n) =>
      n.type === "equipment" ||
      n.type === "facility" ||
      n.type === "experiment"
  );
  const misc = others.filter(
    (n) =>
      n.type !== "figures" &&
      !people.includes(n) &&
      !equipment.includes(n)
  );

  const orbitSlots: Array<{
    kind: "process" | "outer";
    footprint: number;
    place: (cx: number, cy: number, angle: number) => void;
  }> = [];

  for (const cluster of processClusters) {
    orbitSlots.push({
      kind: "process",
      footprint: processClusterFootprint(cluster),
      place: (cx, cy, angle) =>
        layoutProcessCluster(cx, cy, cluster, angle, hubId, hubNodes),
    });
  }

  if (figureBlobs.length > 0) {
    orbitSlots.push({
      kind: "process",
      footprint: gridGroupFootprint(figureBlobs, 8),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, figureBlobs, hubId, `${hubId}:figures`, 8, hubNodes),
    });
  }

  if (people.length > 0) {
    orbitSlots.push({
      kind: "outer",
      footprint: gridGroupFootprint(people, 5),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, people, hubId, `${hubId}:people`, 5, hubNodes),
    });
  }

  if (equipment.length > 0) {
    orbitSlots.push({
      kind: "outer",
      footprint: gridGroupFootprint(equipment, 6),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, equipment, hubId, `${hubId}:equipment`, 6, hubNodes),
    });
  }

  if (misc.length > 0) {
    orbitSlots.push({
      kind: "outer",
      footprint: gridGroupFootprint(misc, 5),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, misc, hubId, `${hubId}:misc`, 5, hubNodes),
    });
  }

  const processSlots = orbitSlots.filter((s) => s.kind === "process");
  const outerSlots = orbitSlots.filter((s) => s.kind === "outer");

  const processFootprints = processSlots.map((s) => s.footprint);
  const outerFootprints = outerSlots.map((s) => s.footprint);

  const docHubR = graphNodeRadius(12) + NODE_GAP_PX * 0.4;
  let innerOrbitR =
    processFootprints.length > 0
      ? Math.max(
          docHubR + minNodeCenterDistance(8) * 0.55,
          orbitRadiusForFootprints(processFootprints, 0.5)
        )
      : docHubR;
  innerOrbitR = Math.min(innerOrbitR, 165);

  processSlots.forEach((slot, i) => {
    const angle =
      (i / Math.max(processSlots.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const cx = center.x + Math.cos(angle) * innerOrbitR;
    const cy = center.y + Math.sin(angle) * innerOrbitR;
    slot.place(cx, cy, angle);
  });

  const maxProcFp = processFootprints.length ? Math.max(...processFootprints) : 0;
  const outerBase =
    innerOrbitR + maxProcFp * 0.55 + minNodeCenterDistance(6) * 0.45;
  const outerOrbitR =
    outerSlots.length > 0
      ? outerBase +
        orbitRadiusForFootprints(outerFootprints, 0.42) * 0.55
      : innerOrbitR;
  const outerR = Math.min(outerOrbitR, innerOrbitR + 220);

  outerSlots.forEach((slot, i) => {
    const angle =
      (i / Math.max(outerSlots.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const cx = center.x + Math.cos(angle) * outerR;
    const cy = center.y + Math.sin(angle) * outerR;
    slot.place(cx, cy, angle);
  });

  resolveCrossClusterOverlaps(hubNodes);
  out.push(...hubNodes);
  return Math.max(innerOrbitR, outerR);
}

export function prepareDocumentHubGraph(
  nodes: GraphNode[],
  links: GraphEdge[]
): { nodes: LayoutNode[]; links: GraphEdge[]; hiddenOrphans: number } {
  if (nodes.length === 0) return { nodes: [], links: [], hiddenOrphans: 0 };

  const docs = nodes.filter((n) => n.type === "article");
  if (docs.length > 0 && docs.length === nodes.length && links.length === 0) {
    const cols = Math.ceil(Math.sqrt(docs.length));
    const rows = Math.ceil(docs.length / cols);
    const positioned: LayoutNode[] = docs.map((doc, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = (col - (cols - 1) / 2) * 420;
      const y = (row - (rows - 1) / 2) * 420;
      return {
        ...doc,
        val: doc.val ?? 12,
        x,
        y,
        fx: x,
        fy: y,
      };
    });
    return { nodes: positioned, links: [], hiddenOrphans: 0 };
  }

  const adj = buildAdjacency(links);

  if (docs.length === 0) {
    return { nodes: [...nodes], links: [...links], hiddenOrphans: 0 };
  }

  const keep = reachableFromDocuments(nodes, adj);
  const filteredNodes = nodes.filter((n) => keep.has(n.id));
  const filteredLinks = links.filter((l) => {
    const [a, b] = linkEndpoints(l);
    return keep.has(a) && keep.has(b);
  });
  const materialToProcess = buildMaterialProcessMap(filteredNodes, filteredLinks);
  const deduped = deduplicateGraphEntities(filteredNodes, filteredLinks);
  const hiddenOrphans =
    nodes.length - filteredNodes.length + deduped.mergedCount;
  const layoutNodes: GraphNode[] = deduped.nodes;
  const layoutLinks = deduped.links;
  const matProcMap = buildMaterialProcessMap(layoutNodes, layoutLinks);

  const byHub = new Map<string, GraphNode[]>();
  for (const node of layoutNodes) {
    const hub = nearestDocument(node.id, docs, adj) ?? docs[0].id;
    if (!byHub.has(hub)) byHub.set(hub, []);
    byHub.get(hub)!.push(node);
  }

  const positioned: LayoutNode[] = [];
  let maxOrbitR = 200;

  const cols = Math.ceil(Math.sqrt(docs.length));
  const hubOffsets = new Map<string, { x: number; y: number }>();

  for (const [hubId, group] of byHub) {
    const temp: LayoutNode[] = [];
    const orbitR = layoutHub(hubId, { x: 0, y: 0 }, group, matProcMap, temp);
    maxOrbitR = Math.max(maxOrbitR, orbitR);
  }

  const hubSpacing = Math.max(420, maxOrbitR * 1.85 + 80);

  docs.forEach((doc, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    hubOffsets.set(doc.id, {
      x: (col - (cols - 1) / 2) * hubSpacing,
      y: (row - (Math.ceil(docs.length / cols) - 1) / 2) * hubSpacing,
    });
  });

  for (const [hubId, group] of byHub) {
    const center = hubOffsets.get(hubId) ?? { x: 0, y: 0 };
    layoutHub(hubId, center, group, matProcMap, positioned);
  }

  return { nodes: positioned, links: layoutLinks, hiddenOrphans };
}

/** Stable 0..1 scalar from node id (deterministic scatter). */
function hashUnit(id: string, salt = 0): number {
  let h = salt;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return (h % 10000) / 10000;
}

function placeDocumentsOnCircle(
  docs: GraphNode[],
  hubRadii: Map<string, number>
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const n = docs.length;
  if (n === 0) return positions;

  if (n === 1) {
    positions.set(docs[0].id, { x: 0, y: 0 });
    return positions;
  }

  const maxHubR = Math.max(320, ...docs.map((d) => hubRadii.get(d.id) ?? 320));
  const minCenterDist = maxHubR * 2 + 160;
  const radius =
    n === 2
      ? minCenterDist / 2
      : minCenterDist / (2 * Math.sin(Math.PI / n));

  docs.forEach((doc, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    positions.set(doc.id, {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    });
  });
  return positions;
}

/**
 * Seed positions for force-directed layout: documents pinned on a circle,
 * entities scattered near their hub without fixed coordinates (no square grids).
 */
export function prepareForceGraphLayout(
  nodes: GraphNode[],
  links: GraphEdge[]
): { nodes: LayoutNode[]; links: GraphEdge[]; hiddenOrphans: number } {
  if (nodes.length === 0) return { nodes: [], links: [], hiddenOrphans: 0 };

  const docs = nodes.filter((n) => n.type === "article");
  if (docs.length > 0 && docs.length === nodes.length && links.length === 0) {
    const cols = Math.ceil(Math.sqrt(docs.length));
    const rows = Math.ceil(docs.length / cols);
    const positioned: LayoutNode[] = docs.map((doc, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = (col - (cols - 1) / 2) * 280;
      const y = (row - (rows - 1) / 2) * 280;
      return {
        ...doc,
        val: doc.val ?? 14,
        x,
        y,
        fx: x,
        fy: y,
        hubId: doc.id,
      };
    });
    return { nodes: positioned, links: [], hiddenOrphans: 0 };
  }

  const adj = buildAdjacency(links);

  if (docs.length === 0) {
    return { nodes: [...nodes], links: [...links], hiddenOrphans: 0 };
  }

  const keep = reachableFromDocuments(nodes, adj);
  const filteredNodes = nodes.filter((n) => keep.has(n.id));
  const filteredLinks = links.filter((l) => {
    const [a, b] = linkEndpoints(l);
    return keep.has(a) && keep.has(b);
  });
  const deduped = deduplicateGraphEntities(filteredNodes, filteredLinks);
  const hiddenOrphans =
    nodes.length - filteredNodes.length + deduped.mergedCount;
  const layoutNodes: GraphNode[] = deduped.nodes;
  const layoutLinks = deduped.links;

  const entitiesByHub = new Map<string, GraphNode[]>();
  for (const node of layoutNodes) {
    if (node.type === "article") continue;
    const hub =
      node.hubId ??
      nearestDocument(node.id, docs, adj) ??
      docs[0]?.id;
    if (!hub) continue;
    if (!entitiesByHub.has(hub)) entitiesByHub.set(hub, []);
    entitiesByHub.get(hub)!.push(node);
  }

  const hubRadii = new Map<string, number>();
  for (const [hubId, entities] of entitiesByHub) {
    hubRadii.set(hubId, estimateHubLayoutRadius(entities));
  }
  for (const doc of docs) {
    if (!hubRadii.has(doc.id)) {
      hubRadii.set(doc.id, CAPSULE_RING_R + 80);
    }
  }

  const docPositions = placeDocumentsOnCircle(docs, hubRadii);
  const positioned: LayoutNode[] = [];

  for (const doc of docs) {
    const { x, y } = docPositions.get(doc.id)!;
    positioned.push({
      ...doc,
      val: doc.val ?? 12,
      x,
      y,
      fx: x,
      fy: y,
      hubId: doc.id,
    });
  }

  for (const [hubId, entities] of entitiesByHub) {
    const hubPos = docPositions.get(hubId) ?? { x: 0, y: 0 };
    const typeClusters = entities.filter((n) => isTypeClusterNode(n));
    const realEntities = entities.filter((n) => !isTypeClusterNode(n));
    positioned.push(...layoutHubTypeClusters(hubId, hubPos, typeClusters));
    positioned.push(...layoutHubEntitiesRadialMap(hubId, hubPos, realEntities));
  }

  return { nodes: positioned, links: layoutLinks, hiddenOrphans };
}

export type HubLayout = {
  nodes: LayoutNode[];
  links: GraphEdge[];
  hiddenOrphans: number;
};

/** Hide entity nodes inside collapsed document hubs until the user expands them. */
export function filterGraphByDocumentExpansion(
  layout: HubLayout,
  expandedDocIds: Set<string>
): { nodes: LayoutNode[]; links: GraphEdge[] } {
  const childCounts = new Map<string, number>();
  for (const node of layout.nodes) {
    if (node.type === "article") continue;
    const hub = node.hubId;
    if (!hub) continue;
    if (node.isTypeCluster && (node.typeClusterCount ?? 0) > 0) {
      childCounts.set(hub, (childCounts.get(hub) ?? 0) + (node.typeClusterCount ?? 0));
    } else if (!isTypeClusterNode(node)) {
      childCounts.set(hub, (childCounts.get(hub) ?? 0) + 1);
    }
  }

  const visibleNodes = layout.nodes.filter((node) => {
    if (node.type === "article") return true;
    const hub = node.hubId;
    return hub ? expandedDocIds.has(hub) : true;
  });

  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  const visibleLinks = layout.links.filter((link) => {
    const [a, b] = linkEndpoints(link);
    return visibleIds.has(a) && visibleIds.has(b);
  });

  const nodes = visibleNodes.map((node) => {
    if (node.type !== "article") return node;
    const count = childCounts.get(node.id) ?? 0;
    const collapsed = count > 0 && !expandedDocIds.has(node.id);
    if (!collapsed) return node;
    return {
      ...node,
      val: Math.max(node.val ?? 12, 16),
      collapsedChildCount: count,
      isCollapsedHub: true,
    };
  });

  return { nodes, links: visibleLinks };
}

/** Shift layout so a specific node sits at the origin (screen center after centerAt). */
export function centerLayoutOnNode<
  T extends { id: string; x?: number; y?: number; fx?: number; fy?: number },
>(nodes: T[], nodeId: string): T[] {
  const anchor = nodes.find((n) => n.id === nodeId);
  if (!anchor || anchor.x == null || anchor.y == null) return nodes;
  const ox = anchor.x;
  const oy = anchor.y;
  return nodes.map((n) => {
    if (n.x == null || n.y == null) return n;
    const out: T = { ...n, x: n.x - ox, y: n.y - oy };
    if (n.fx != null) out.fx = n.fx - ox;
    if (n.fy != null) out.fy = n.fy - oy;
    return out;
  });
}

/** Shift layout so the visible subgraph is centered at the origin (better zoom-to-fit). */
export function recenterLayoutNodes<T extends { x?: number; y?: number; fx?: number; fy?: number }>(
  nodes: T[]
): T[] {
  const positioned = nodes.filter((n) => n.x != null && n.y != null);
  if (positioned.length === 0) return nodes;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const n of positioned) {
    minX = Math.min(minX, n.x!);
    maxX = Math.max(maxX, n.x!);
    minY = Math.min(minY, n.y!);
    maxY = Math.max(maxY, n.y!);
  }
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  if (Math.abs(cx) < 1 && Math.abs(cy) < 1) return nodes;

  return nodes.map((n) => {
    if (n.x == null || n.y == null) return n;
    const x = n.x - cx;
    const y = n.y - cy;
    const out: T = { ...n, x, y };
    if (n.fx != null) out.fx = n.fx - cx;
    if (n.fy != null) out.fy = n.fy - cy;
    return out;
  });
}

/** Compact local layout for Q&A query-focus (avoids hub-scale coordinates). */
export function layoutQueryFocusNodes(
  nodes: GraphNode[],
  primaryIds?: Set<string>,
  chainLinks?: GraphEdge[]
): LayoutNode[] {
  if (nodes.length === 0) return [];

  const stripLayout = (node: GraphNode, x: number, y: number): LayoutNode => ({
    ...node,
    x,
    y,
    fx: x,
    fy: y,
    layoutRole: undefined,
    clusterId: undefined,
    clusterType: undefined,
    clusterCx: undefined,
    clusterCy: undefined,
    clusterSize: undefined,
  });

  const ordered = orderNodesAlongChain(nodes, chainLinks);
  if (ordered.length >= 2) {
    const count = ordered.length;
    const radius = Math.max(90, Math.min(220, 40 + count * 14));
    return ordered.map((node, i) => {
      const angle = (2 * Math.PI * i) / count - Math.PI / 2;
      const isPrimary = primaryIds?.has(node.id);
      const r = isPrimary ? radius * 0.68 : radius;
      const x = Math.cos(angle) * r;
      const y = Math.sin(angle) * r;
      return stripLayout(node, x, y);
    });
  }

  const sorted = [...nodes].sort((a, b) => {
    const ap = primaryIds?.has(a.id) ? 0 : 1;
    const bp = primaryIds?.has(b.id) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    return (a.name ?? a.id).localeCompare(b.name ?? b.id);
  });

  const count = sorted.length;
  const radius = Math.max(56, Math.min(140, 32 * Math.sqrt(count)));

  return sorted.map((node, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    const isPrimary = primaryIds?.has(node.id);
    const r = isPrimary ? radius * 0.55 : radius;
    const x = Math.cos(angle) * r;
    const y = Math.sin(angle) * r;
    return stripLayout(node, x, y);
  });
}

function orderNodesAlongChain(
  nodes: GraphNode[],
  links: GraphEdge[] | undefined
): GraphNode[] {
  if (!links?.length || nodes.length < 2) return [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const degree = new Map<string, number>();
  const adj = new Map<string, string[]>();

  for (const link of links) {
    const a = String(link.source);
    const b = String(link.target);
    if (!byId.has(a) || !byId.has(b)) continue;
    adj.set(a, [...(adj.get(a) ?? []), b]);
    adj.set(b, [...(adj.get(b) ?? []), a]);
    degree.set(a, (degree.get(a) ?? 0) + 1);
    degree.set(b, (degree.get(b) ?? 0) + 1);
  }
  if (adj.size === 0) return [];

  let start = [...degree.entries()].find(([, d]) => d === 1)?.[0];
  if (!start) start = nodes[0]?.id;
  if (!start) return [];

  const ordered: GraphNode[] = [];
  const seen = new Set<string>();
  let cur: string | undefined = start;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const node = byId.get(cur);
    if (node) ordered.push(node);
    const next: string | undefined = (adj.get(cur) ?? []).find((nb) => !seen.has(nb));
    cur = next;
  }
  for (const node of nodes) {
    if (!seen.has(node.id)) ordered.push(node);
  }
  return ordered;
}
