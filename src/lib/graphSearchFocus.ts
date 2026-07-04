import type { GraphEdge, GraphNode, SearchResult } from "@/lib/types";

const MAX_VISIBLE = 24;
const MAX_PRIMARY = 10;
const MAX_GRAPH_MATCHES = 8;
const MIN_PRIMARY_SCORE = 42;
const MIN_CONNECTOR_SCORE = 18;

/** Low-value node types unless they directly match the query/answer. */
const EXPANSION_SKIP_TYPES = new Set<GraphNode["type"]>([
  "equipment",
  "facility",
  "figures",
  "expert",
  "team",
  "article",
]);

const GENERIC_TERMS = new Set([
  "acid",
  "and",
  "are",
  "for",
  "from",
  "gas",
  "has",
  "mix",
  "not",
  "ore",
  "the",
  "unit",
  "units",
  "with",
  "как",
  "какие",
  "какой",
  "при",
  "это",
]);

export interface GraphSearchFocus {
  visibleIds: string[];
  primaryIds: string[];
  documentIds: string[];
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

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function tokenize(text: string): string[] {
  return normalize(text)
    .split(/[^a-z0-9а-яё]+/i)
    .map((t) => t.trim())
    .filter((t) => t.length >= 4 && !GENERIC_TERMS.has(t));
}

function extractPhrases(result: SearchResult): string[] {
  const phrases: string[] = [];
  const seen = new Set<string>();

  const push = (raw: string | undefined, minLen = 4) => {
    const v = raw?.trim();
    if (!v || v.length < minLen) return;
    const key = normalize(v);
    if (seen.has(key)) return;
    seen.add(key);
    phrases.push(v);
  };

  push(result.query, 4);
  push(result.parsed.material, 4);
  push(result.parsed.mode, 4);
  push(result.parsed.property, 4);
  push(result.parsed.geography, 4);
  push(result.parsed.team, 4);
  for (const kw of result.parsed.keywords ?? []) push(kw, 4);

  for (const row of result.structuredExperiments ?? []) {
    push(row.material, 4);
    push(row.process, 4);
    push(row.regime, 4);
  }

  const narrative = result.narrative ?? "";
  for (const line of narrative.split(/\n+/)) {
    const cleaned = line.replace(/^[\s•\-*\d.)]+/, "").trim();
    if (cleaned.length >= 6) push(cleaned, 6);
    const propMatch = cleaned.match(/^([^:]{4,60}):\s*.+/);
    if (propMatch) push(propMatch[1], 4);
  }

  for (const src of result.sources.slice(0, 6)) {
    const snippet = src.text?.slice(0, 220) ?? "";
    for (const token of tokenize(snippet)) push(token, 4);
  }

  for (const token of tokenize(result.query)) push(token, 4);

  return phrases;
}

function nodeHaystack(node: GraphNode): string {
  return normalize(
    [
      node.name,
      node.typeSummary,
      node.regimeName,
      node.conclusionText,
      ...(node.components ?? []),
      ...(node.members ?? []),
    ]
      .filter(Boolean)
      .join(" ")
  );
}

function scoreNodeForPhrases(node: GraphNode, phrases: string[]): number {
  const hay = nodeHaystack(node);
  const name = normalize(node.name ?? "");
  let best = 0;

  for (const phrase of phrases) {
    const p = normalize(phrase);
    if (!p) continue;

    if (name === p) best = Math.max(best, 100);
    else if (name.includes(p) && p.length >= 5) best = Math.max(best, 82);
    else if (p.includes(name) && name.length >= 5) best = Math.max(best, 78);
    else if (new RegExp(`\\b${escapeRegExp(p)}\\b`, "i").test(hay)) {
      best = Math.max(best, p.length >= 8 ? 72 : 58);
    } else if (hay.includes(p) && p.length >= 7) {
      best = Math.max(best, 48);
    }
  }

  if (node.type === "property" && best > 0) best += 8;
  if (node.type === "experiment" && best > 0) best += 6;
  if (node.type === "material" && best > 0) best += 4;
  if (EXPANSION_SKIP_TYPES.has(node.type) && best < 70) best = Math.min(best, 24);

  return best;
}

function scoreNodes(
  nodes: GraphNode[],
  phrases: string[],
  bonus: Map<string, number>
): Map<string, number> {
  const scores = new Map<string, number>();
  for (const node of nodes) {
    let score = scoreNodeForPhrases(node, phrases);
    score += bonus.get(node.id) ?? 0;
    if (score > 0) scores.set(node.id, score);
  }
  return scores;
}

function topIds(scores: Map<string, number>, limit: number, minScore: number): string[] {
  return [...scores.entries()]
    .filter(([, score]) => score >= minScore)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([id]) => id);
}

function shortestPath(
  from: string,
  to: string,
  adj: Map<string, Set<string>>,
  allowed: Set<string>
): string[] | null {
  if (from === to) return [from];
  const queue: string[] = [from];
  const prev = new Map<string, string | null>([[from, null]]);

  while (queue.length) {
    const cur = queue.shift()!;
    for (const nb of adj.get(cur) ?? []) {
      if (!allowed.has(nb) || prev.has(nb)) continue;
      prev.set(nb, cur);
      if (nb === to) {
        const path: string[] = [];
        let walk: string | null = to;
        while (walk) {
          path.unshift(walk);
          walk = prev.get(walk) ?? null;
        }
        return path;
      }
      queue.push(nb);
    }
  }
  return null;
}

function bridgePrimarySeeds(
  primary: Set<string>,
  nodes: GraphNode[],
  adj: Map<string, Set<string>>,
  scores: Map<string, number>
): Set<string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const allowed = new Set<string>();
  for (const node of nodes) {
    const score = scores.get(node.id) ?? 0;
    const type = node.type;
    if (score >= MIN_CONNECTOR_SCORE) allowed.add(node.id);
    else if (!EXPANSION_SKIP_TYPES.has(type)) allowed.add(node.id);
  }

  const bridged = new Set<string>(primary);
  const primaryList = [...primary];

  for (let i = 0; i < primaryList.length; i++) {
    for (let j = i + 1; j < primaryList.length; j++) {
      const path = shortestPath(primaryList[i], primaryList[j], adj, allowed);
      if (!path) continue;
      if (path.length > 4) continue;
      for (const id of path) {
        const node = byId.get(id);
        if (!node) continue;
        if (EXPANSION_SKIP_TYPES.has(node.type) && !primary.has(id)) continue;
        bridged.add(id);
      }
    }
  }

  return bridged;
}

function capByScore(ids: Set<string>, scores: Map<string, number>, limit: number): string[] {
  return [...ids]
    .map((id) => ({ id, score: scores.get(id) ?? 0 }))
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((row) => row.id);
}

function documentIdsForNodes(
  nodes: GraphNode[],
  links: GraphEdge[],
  visible: Set<string>
): string[] {
  const docs = nodes.filter((n) => n.type === "article");
  const docIdSet = new Set(docs.map((d) => d.id));
  const adj = buildAdjacency(links);
  const out = new Set<string>();

  for (const nodeId of visible) {
    if (docIdSet.has(nodeId)) {
      out.add(nodeId);
      continue;
    }
    const queue = [nodeId];
    const seen = new Set<string>([nodeId]);
    while (queue.length) {
      const cur = queue.shift()!;
      for (const nb of adj.get(cur) ?? []) {
        if (seen.has(nb)) continue;
        seen.add(nb);
        if (docIdSet.has(nb)) {
          out.add(nb);
          break;
        }
        queue.push(nb);
      }
    }
  }

  return [...out];
}

/** Tight subgraph: only nodes that directly support the current Q&A. */
export function computeSearchFocus(
  nodes: GraphNode[],
  links: GraphEdge[],
  result: SearchResult | null
): GraphSearchFocus | null {
  if (!result || nodes.length === 0) return null;

  const phrases = extractPhrases(result);
  const bonus = new Map<string, number>();

  for (const id of (result.graphMatchIds ?? []).slice(0, MAX_GRAPH_MATCHES)) {
    if (id) bonus.set(String(id), (bonus.get(String(id)) ?? 0) + 90);
  }

  for (const row of (result.structuredExperiments ?? []).slice(0, 8)) {
    if (row.experiment_id) bonus.set(String(row.experiment_id), 85);
    if (row.document_id) bonus.set(String(row.document_id), 20);
  }

  for (const exp of result.experiments.slice(0, 5)) {
    bonus.set(exp.experiment.id, (bonus.get(exp.experiment.id) ?? 0) + 70);
  }

  const scores = scoreNodes(nodes, phrases, bonus);
  if (scores.size === 0 && phrases.length === 0 && bonus.size === 0) {
    return null;
  }

  let primaryIds = topIds(scores, MAX_PRIMARY, MIN_PRIMARY_SCORE);
  if (primaryIds.length === 0) {
    primaryIds = topIds(scores, Math.min(6, MAX_PRIMARY), 30);
  }
  if (primaryIds.length === 0) return null;

  const primary = new Set(primaryIds);
  const adj = buildAdjacency(links);
  let visible = bridgePrimarySeeds(primary, nodes, adj, scores);

  if (visible.size < primary.size) {
    for (const id of primary) visible.add(id);
  }

  const visibleIds = capByScore(visible, scores, MAX_VISIBLE);
  const visibleSet = new Set(visibleIds);
  const documentIds = documentIdsForNodes(nodes, links, visibleSet);

  return {
    visibleIds,
    primaryIds: primaryIds.filter((id) => visibleSet.has(id)),
    documentIds,
  };
}

/** @deprecated Use computeSearchFocus */
export function computeSearchFocusNodeIds(
  nodes: GraphNode[],
  links: GraphEdge[],
  result: SearchResult | null
): string[] | null {
  return computeSearchFocus(nodes, links, result)?.visibleIds ?? null;
}

export function documentIdsFromFocus(
  nodes: GraphNode[],
  links: GraphEdge[],
  focusIds: string[] | null
): string[] {
  if (!focusIds?.length) return [];
  return documentIdsForNodes(nodes, links, new Set(focusIds));
}
