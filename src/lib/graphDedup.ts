import type { EntityType, GraphEdge, GraphNode } from "@/lib/types";
import {
  canonicalEntityKey,
  pluralTokenKey,
  propertyBaseLabel,
  tokenSortKey,
} from "@/lib/entityCanonical";

const DEDUP_TYPES = new Set<EntityType>([
  "material",
  "process",
  "equipment",
  "facility",
  "property",
  "expert",
  "team",
  "mode",
]);

function linkEndpoints(link: GraphEdge): [string, string] {
  return [String(link.source), String(link.target)];
}

function degreeMap(links: GraphEdge[]): Map<string, number> {
  const deg = new Map<string, number>();
  const bump = (id: string) => deg.set(id, (deg.get(id) ?? 0) + 1);
  for (const link of links) {
    const [a, b] = linkEndpoints(link);
    bump(a);
    bump(b);
  }
  return deg;
}

function dedupKeyForNode(node: GraphNode): string | null {
  if (!DEDUP_TYPES.has(node.type)) return null;

  if (node.type === "material" && node.components?.length) {
    const keys = [...new Set(node.components.map((c) => canonicalEntityKey(c)).filter(Boolean))].sort();
    if (keys.length === 1) return `material:${keys[0]}`;
    if (keys.length > 1) return `material:blend:${keys.join("+")}`;
  }

  let label = node.name?.trim() ?? "";
  if (node.type === "property") label = propertyBaseLabel(label);

  const glossary = canonicalEntityKey(label);
  const tokenKey = pluralTokenKey(label);
  const base = glossary || tokenKey;
  if (!base) return null;

  return `${node.type}:${base}`;
}

function pickCanonicalNode(group: GraphNode[], degrees: Map<string, number>): GraphNode {
  return [...group].sort((a, b) => {
    const degA = degrees.get(a.id) ?? 0;
    const degB = degrees.get(b.id) ?? 0;
    if (degB !== degA) return degB - degA;
    const lenA = (a.name ?? "").length;
    const lenB = (b.name ?? "").length;
    if (lenB !== lenA) return lenB - lenA;
    return a.id.localeCompare(b.id);
  })[0];
}

function mergeContainmentGroups(
  byKey: Map<string, GraphNode[]>,
  degrees: Map<string, number>
): Map<string, GraphNode[]> {
  const entries = [...byKey.entries()].sort((a, b) => a[0].length - b[0].length);
  const merged = new Map<string, GraphNode[]>();
  const absorbed = new Set<string>();

  for (let i = 0; i < entries.length; i++) {
    const [keyA, groupA] = entries[i];
    if (absorbed.has(keyA)) continue;

    const typeA = groupA[0]?.type;
    let combined = [...groupA];

    for (let j = i + 1; j < entries.length; j++) {
      const [keyB, groupB] = entries[j];
      if (absorbed.has(keyB)) continue;
      if (groupB[0]?.type !== typeA) continue;

      const shorter = keyA.length <= keyB.length ? keyA : keyB;
      const longer = keyA.length > keyB.length ? keyA : keyB;
      if (!longer.includes(shorter) || shorter === longer) continue;

      const repA = pickCanonicalNode(combined, degrees).name ?? "";
      const repB = pickCanonicalNode(groupB, degrees).name ?? "";
      const tokA = tokenSortKey(repA);
      const tokB = tokenSortKey(repB);
      if (tokA !== tokB && !tokA.includes(tokB) && !tokB.includes(tokA)) continue;

      combined = [...combined, ...groupB];
      absorbed.add(keyB);
    }

    const canonical = pickCanonicalNode(combined, degrees);
    const finalKey = dedupKeyForNode(canonical) ?? keyA;
    const existing = merged.get(finalKey) ?? [];
    merged.set(finalKey, [...existing, ...combined]);
  }

  return merged;
}

export interface DedupedGraph {
  nodes: GraphNode[];
  links: GraphEdge[];
  mergedCount: number;
  idRemap: Map<string, string>;
}

/**
 * Collapse duplicate entity blobs that share the same real-world identity.
 * Keeps the best-connected node per group and rewires edges.
 */
export function deduplicateGraphEntities(
  nodes: GraphNode[],
  links: GraphEdge[]
): DedupedGraph {
  const degrees = degreeMap(links);
  const byKey = new Map<string, GraphNode[]>();

  for (const node of nodes) {
    const key = dedupKeyForNode(node);
    if (!key) continue;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key)!.push(node);
  }

  const mergedGroups = mergeContainmentGroups(byKey, degrees);
  const idRemap = new Map<string, string>();
  const dropIds = new Set<string>();
  let mergedCount = 0;

  for (const group of mergedGroups.values()) {
    if (group.length <= 1) continue;
    const keeper = pickCanonicalNode(group, degrees);
    for (const node of group) {
      if (node.id === keeper.id) continue;
      idRemap.set(node.id, keeper.id);
      dropIds.add(node.id);
      mergedCount += 1;
    }
  }

  if (mergedCount === 0) {
    return { nodes, links, mergedCount: 0, idRemap };
  }

  const remapId = (id: string): string => {
    let cur = id;
    const seen = new Set<string>();
    while (idRemap.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      cur = idRemap.get(cur)!;
    }
    return cur;
  };

  const keptNodes = nodes
    .filter((n) => !dropIds.has(n.id))
    .map((n) => {
      const aliases = new Set<string>();
      for (const [dupId, canonId] of idRemap) {
        if (canonId !== n.id) continue;
        const dup = nodes.find((x) => x.id === dupId);
        if (dup?.name && dup.name !== n.name) aliases.add(dup.name);
      }
      if (aliases.size === 0) return n;
      const mergedAliases = [...new Set([...(n.components ?? []), ...aliases])];
      return { ...n, components: n.type === "material" ? mergedAliases : n.components };
    });

  const seenLinks = new Set<string>();
  const keptLinks: GraphEdge[] = [];
  for (const link of links) {
    const src = remapId(String(link.source));
    const tgt = remapId(String(link.target));
    if (src === tgt) continue;
    const key = `${src}|${tgt}|${link.relation}`;
    if (seenLinks.has(key)) continue;
    seenLinks.add(key);
    keptLinks.push({ ...link, source: src, target: tgt });
  }

  return {
    nodes: keptNodes,
    links: keptLinks,
    mergedCount,
    idRemap,
  };
}
