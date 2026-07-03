import type { GraphEdge, GraphNode } from "@/lib/types";
import {
  graphCollisionRadius,
  graphNodeRadius,
  minNodeCenterDistance,
  NODE_GAP_PX,
  ringRadiusForCount,
} from "@/lib/graph";

type LayoutNode = GraphNode & {
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
  clusterId?: string;
};

type ProcessCluster = {
  id: string;
  process: GraphNode | null;
  satellites: GraphNode[];
};

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
  const keep = new Set<string>();
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
  clusterId?: string
): LayoutNode {
  return { ...node, x, y, fx: x, fy: y, clusterId };
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
  clusterId: string,
  val: number,
  out: LayoutNode[]
): void {
  const n = nodes.length;
  if (n === 1) {
    out.push(pin(nodes[0], cx, cy, clusterId));
    return;
  }
  const ringR = Math.max(minNodeCenterDistance(val), ringRadiusForCount(n, val));
  nodes.forEach((node, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    out.push(pin(node, cx + Math.cos(a) * ringR, cy + Math.sin(a) * ringR, clusterId));
  });
}

function layoutProcessCluster(
  cx: number,
  cy: number,
  cluster: ProcessCluster,
  outwardAngle: number,
  out: LayoutNode[]
): void {
  const gap = minNodeCenterDistance(8) * 0.85;
  const satellites = cluster.satellites;

  if (!cluster.process) {
    placeOnRing(cx, cy, satellites, cluster.id, 7, out);
    return;
  }

  out.push(pin(cluster.process, cx, cy, cluster.id));

  if (satellites.length === 0) return;

  if (satellites.length === 1) {
    out.push(
      pin(
        satellites[0],
        cx + Math.cos(outwardAngle) * gap,
        cy + Math.sin(outwardAngle) * gap,
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
        cluster.id
      )
    );
  });
}

function layoutTightGroup(
  cx: number,
  cy: number,
  nodes: GraphNode[],
  clusterId: string,
  fallbackVal: number,
  out: LayoutNode[]
): void {
  if (nodes.length === 0) return;
  if (nodes.length === 1) {
    out.push(pin(nodes[0], cx, cy, clusterId));
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
    out.push(pin(node, x, y, clusterId));
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

function canonicalizeProcesses(
  nodes: GraphNode[],
  links: GraphEdge[],
  materialToProcess: Map<string, string>
): {
  nodes: GraphNode[];
  links: GraphEdge[];
  materialToProcess: Map<string, string>;
} {
  const processes = nodes.filter((n) => n.type === "process");
  if (processes.length <= 1) {
    return { nodes, links, materialToProcess };
  }

  const byName = new Map<string, GraphNode[]>();
  for (const proc of processes) {
    const key = (proc.name ?? proc.id).toLowerCase().trim();
    if (!byName.has(key)) byName.set(key, []);
    byName.get(key)!.push(proc);
  }

  const idToCanonical = new Map<string, string>();
  const canonicalIds = new Set<string>();

  for (const group of byName.values()) {
    let best = group[0];
    let bestCount = -1;
    for (const proc of group) {
      const count = [...materialToProcess.values()].filter((pid) => pid === proc.id).length;
      if (count > bestCount) {
        bestCount = count;
        best = proc;
      }
    }
    for (const proc of group) {
      idToCanonical.set(proc.id, best.id);
      if (proc.id === best.id) canonicalIds.add(proc.id);
    }
  }

  if (canonicalIds.size === processes.length) {
    return { nodes, links, materialToProcess };
  }

  const filteredNodes = nodes.filter(
    (n) => n.type !== "process" || canonicalIds.has(n.id)
  );

  const remappedMat = new Map<string, string>();
  for (const [matId, procId] of materialToProcess) {
    remappedMat.set(matId, idToCanonical.get(procId) ?? procId);
  }

  const remapId = (id: string): string => idToCanonical.get(id) ?? id;

  const seenLinks = new Set<string>();
  const filteredLinks: GraphEdge[] = [];
  for (const link of links) {
    const [a, b] = linkEndpoints(link);
    const src = remapId(a);
    const tgt = remapId(b);
    if (src === tgt) continue;
    const key = `${src}|${tgt}|${link.relation}`;
    if (seenLinks.has(key)) continue;
    seenLinks.add(key);
    filteredLinks.push({ ...link, source: src, target: tgt });
  }

  return {
    nodes: filteredNodes,
    links: filteredLinks,
    materialToProcess: remappedMat,
  };
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
  const equipment = others.filter(
    (n) =>
      n.type === "equipment" ||
      n.type === "facility" ||
      n.type === "experiment"
  );
  const misc = others.filter(
    (n) => !people.includes(n) && !equipment.includes(n)
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
        layoutProcessCluster(cx, cy, cluster, angle, hubNodes),
    });
  }

  if (people.length > 0) {
    orbitSlots.push({
      kind: "outer",
      footprint: gridGroupFootprint(people, 5),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, people, `${hubId}:people`, 5, hubNodes),
    });
  }

  if (equipment.length > 0) {
    orbitSlots.push({
      kind: "outer",
      footprint: gridGroupFootprint(equipment, 6),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, equipment, `${hubId}:equipment`, 6, hubNodes),
    });
  }

  if (misc.length > 0) {
    orbitSlots.push({
      kind: "outer",
      footprint: gridGroupFootprint(misc, 5),
      place: (cx, cy) =>
        layoutTightGroup(cx, cy, misc, `${hubId}:misc`, 5, hubNodes),
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

  const adj = buildAdjacency(links);
  const docs = nodes.filter((n) => n.type === "article");

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
  const canonical = canonicalizeProcesses(
    filteredNodes,
    filteredLinks,
    materialToProcess
  );
  const hiddenOrphans =
    nodes.length -
    filteredNodes.length +
    (filteredNodes.length - canonical.nodes.length);
  const layoutNodes: GraphNode[] = canonical.nodes;
  const layoutLinks = canonical.links;
  const matProcMap = canonical.materialToProcess;

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
