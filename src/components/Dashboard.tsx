"use client";

import { useState, useCallback, useEffect, useRef, useMemo, type Dispatch, type SetStateAction } from "react";
import { SearchBar } from "@/components/SearchBar";
import { ExperimentCard } from "@/components/ExperimentCard";
import { Timeline } from "@/components/Timeline";
import { EntityPanel } from "@/components/EntityPanel";
import { EntityBrowsePanel } from "@/components/EntityBrowsePanel";
import { StatsBar } from "@/components/StatsBar";
import { DocumentUpload } from "@/components/DocumentUpload";
import { DocumentFilter, type DocumentOption } from "@/components/DocumentFilter";
import { SourceExcerpts } from "@/components/SourceExcerpts";
import { checkBackendHealth, backendApi, GRAPH_OVERVIEW_LIMIT, GRAPH_TYPE_PAGE_LIMIT } from "@/lib/api/backend";
import { backendSearch, backendGraphToFrontend } from "@/lib/adapters/backend";
import { backendDocumentToArticle, experimentDetailsToEntity, graphNodeToEntity, propertyDetailsToEntity } from "@/lib/entityFromGraph";
import { getNodeConnections, type NodeConnection } from "@/lib/graphConnections";
import { computeSearchFocus } from "@/lib/graphSearchFocus";
import { INGEST_COMPLETE_EVENT, INGEST_START_EVENT } from "@/lib/ingestRouteEvents";
import { mergeGraphSnapshots } from "@/lib/graphMerge";
import {
  buildTypeClusterGraph,
  entityTypeToNeo4jLabel,
  expandedTypeKey,
  isTypeClusterNode,
  parseTypeClusterId,
  removeDocumentHierarchy,
  snapshotTypeClusterMembers,
} from "@/lib/graphHierarchy";
import { fetchAllTypeClusterMembers } from "@/lib/graphTypeMembers";
import { getEntityLabel } from "@/lib/graph";
import { QueryFilters } from "@/components/QueryFilters";
import { ContradictionsPanel } from "@/components/ContradictionsPanel";
import { downloadText, exportSearchJson, exportSearchMarkdown } from "@/lib/exportResults";
import { parseQuery, parsedToStructured } from "@/lib/query";
import type { Entity, GraphEdge, GraphNode, SearchResult, EntityType, StructuredFilters } from "@/lib/types";
import { Network, MessageSquareQuote, Server, ServerOff, AlertCircle, Download, Loader2 } from "lucide-react";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ModelSwitcher } from "@/components/ModelSwitcher";
import { useI18n } from "@/lib/i18n/I18nProvider";

import { GraphView } from "@/components/GraphView";

type PanelSnapshot = {
  selectedNodeId: string;
  panelEntity: Entity;
  panelGroupMembers: GraphNode[];
  panelGroupMembersTotal: number;
  panelGroupMembersLoading: boolean;
  panelConnections: NodeConnection[];
  panelLoading: boolean;
};

export function Dashboard() {
  const { t, locale } = useI18n();
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedExpId, setSelectedExpId] = useState<string | null>(null);
  const [panelEntity, setPanelEntity] = useState<Entity | null>(null);
  const [panelConnections, setPanelConnections] = useState<NodeConnection[]>([]);
  const [panelGroupMembers, setPanelGroupMembers] = useState<GraphNode[] | undefined>(undefined);
  const [panelGroupMembersTotal, setPanelGroupMembersTotal] = useState(0);
  const [panelGroupMembersLoading, setPanelGroupMembersLoading] = useState(false);
  const [panelBack, setPanelBack] = useState<PanelSnapshot | null>(null);
  const [panelLoading, setPanelLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [ingestActive, setIngestActive] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [statsRefreshKey, setStatsRefreshKey] = useState(0);
  const [graphSnapshot, setGraphSnapshot] = useState<{
    nodes: GraphNode[];
    links: GraphEdge[];
  }>({ nodes: [], links: [] });
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphTypeFilter, setGraphTypeFilter] = useState<EntityType | null>(null);
  const [expandedDocIds, setExpandedDocIds] = useState<Set<string>>(() => new Set());
  const [documents, setDocuments] = useState<DocumentOption[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [structuredFilters, setStructuredFilters] = useState<StructuredFilters>({});
  const [graphFocusDismissed, setGraphFocusDismissed] = useState(false);
  const [expandingDocId, setExpandingDocId] = useState<string | null>(null);
  const [expandedTypeKeys, setExpandedTypeKeys] = useState<Set<string>>(() => new Set());
  const [expandingTypeKey, setExpandingTypeKey] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<HTMLDivElement>(null);
  const entityDedupeDoneRef = useRef(false);
  const loadedDocSummariesRef = useRef<Set<string>>(new Set());
  const loadedTypeKeysRef = useRef<Set<string>>(new Set());
  const panelFetchGenRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const onStart = () => setIngestActive(true);
    const onComplete = () => setIngestActive(false);
    window.addEventListener(INGEST_START_EVENT, onStart);
    window.addEventListener(INGEST_COMPLETE_EVENT, onComplete);
    return () => {
      window.removeEventListener(INGEST_START_EVENT, onStart);
      window.removeEventListener(INGEST_COMPLETE_EVENT, onComplete);
    };
  }, []);

  useEffect(() => {
    const syncIngestActive = async () => {
      try {
        const status = await backendApi.ingestActive();
        setIngestActive(status.active);
      } catch {
        /* backend offline */
      }
    };
    void syncIngestActive();
    const interval = window.setInterval(syncIngestActive, 3000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!graphTypeFilter || panelEntity) return;
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      requestAnimationFrame(() => {
        panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
  }, [graphTypeFilter, panelEntity]);

  const effectiveBackendOnline = backendOnline || ingestActive;
  const searchBlocked = !backendOnline || ingestActive;

  const searchFocus = useMemo(
    () => computeSearchFocus(graphSnapshot.nodes, graphSnapshot.links, result),
    [graphSnapshot.nodes, graphSnapshot.links, result]
  );

  const loadDocumentSubgraph = useCallback(
    async (docId: string) => {
      if (loadedDocSummariesRef.current.has(docId)) return;
      setExpandingDocId(docId);
      try {
        const summary = await backendApi.documentEntitySummary(docId).catch(() => null);
        if (!summary) return;
        loadedDocSummariesRef.current.add(docId);
        const virtual = buildTypeClusterGraph(docId, summary.types, (type) =>
          getEntityLabel(type, locale)
        );
        setGraphSnapshot((prev) => mergeGraphSnapshots(prev, virtual));
      } finally {
        setExpandingDocId(null);
      }
    },
    [locale]
  );

  const focusDocumentInGraph = useCallback(
    (documentId: string) => {
      setSelectedDocumentId(documentId);
      setExpandedDocIds(new Set());
      setExpandedTypeKeys(new Set());
      setSelectedNodeId(null);
      setGraphFocusDismissed(true);
      void loadDocumentSubgraph(documentId);
      requestAnimationFrame(() => {
        graphRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    },
    [loadDocumentSubgraph]
  );

  const loadTypeClusterEntities = useCallback(async (docId: string, entityType: EntityType) => {
    const key = expandedTypeKey(docId, entityType);
    if (loadedTypeKeysRef.current.has(key)) {
      setExpandedTypeKeys((prev) => new Set(prev).add(key));
      return;
    }
    setExpandingTypeKey(key);
    try {
      const neo4jLabel = entityTypeToNeo4jLabel(entityType);
      if (!neo4jLabel) return;

      let offset = 0;
      const pageSize = GRAPH_TYPE_PAGE_LIMIT;
      const allNodes: GraphNode[] = [];
      const allLinks: GraphEdge[] = [];

      while (true) {
        const page = await backendApi
          .documentEntitiesByType(docId, neo4jLabel, pageSize, offset)
          .catch(() => null);
        if (!page) break;

        const graph = backendGraphToFrontend({ nodes: page.nodes, edges: page.edges });
        for (const node of graph.nodes) {
          allNodes.push({
            ...node,
            hubId: docId,
            documentId: docId,
          });
        }
        for (const link of graph.links) {
          allLinks.push(link);
        }

        if (!page.has_more) break;
        offset += pageSize;
      }

      loadedTypeKeysRef.current.add(key);
      setExpandedTypeKeys((prev) => new Set(prev).add(key));
      setGraphSnapshot((prev) => mergeGraphSnapshots(prev, { nodes: allNodes, links: allLinks }));
    } finally {
      setExpandingTypeKey(null);
    }
  }, []);

  const handleDocumentCollapse = useCallback((docId: string) => {
    loadedDocSummariesRef.current.delete(docId);
    for (const key of [...loadedTypeKeysRef.current]) {
      if (key.startsWith(`${docId}:`)) loadedTypeKeysRef.current.delete(key);
    }
    setExpandedTypeKeys((prev) => {
      const next = new Set(prev);
      for (const key of prev) {
        if (key.startsWith(`${docId}:`)) next.delete(key);
      }
      return next;
    });
    setGraphSnapshot((prev) => removeDocumentHierarchy(prev, docId));
  }, []);

  const refreshGraphSnapshot = useCallback(async () => {
    setGraphLoading(true);
    try {
      loadedDocSummariesRef.current.clear();
      loadedTypeKeysRef.current.clear();

      const hubs = await backendApi
        .exploreGraph(GRAPH_OVERVIEW_LIMIT, undefined, true)
        .catch(() => null);
      if (!hubs) return;
      const graph = backendGraphToFrontend(hubs);
      setGraphSnapshot(graph);
      setExpandedDocIds(new Set());
      setExpandedTypeKeys(new Set());
      setResult((prev) => (prev ? { ...prev, graph } : prev));

      if (!entityDedupeDoneRef.current) {
        entityDedupeDoneRef.current = true;
        void backendApi.reconcileDuplicateEntities().catch(() => null);
      }
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const refreshBackendStatus = useCallback(async () => {
    const ok = await checkBackendHealth();
    if (ok || !ingestActive) {
      setBackendOnline(ok);
    }
    return ok || ingestActive;
  }, [ingestActive]);

  const refreshAfterIngest = useCallback(async () => {
    await refreshBackendStatus();
    setStatsRefreshKey((k) => k + 1);
    await refreshGraphSnapshot();
    const docs = await backendApi.listDocuments().catch(() => []);
    setDocuments(
      docs.map((d) => ({
        id: d.id,
        title: d.title || d.id.slice(0, 8),
      }))
    );
  }, [refreshBackendStatus, refreshGraphSnapshot]);

  useEffect(() => {
    refreshBackendStatus();
    const interval = setInterval(refreshBackendStatus, 15000);
    return () => clearInterval(interval);
  }, [refreshBackendStatus]);

  useEffect(() => {
    if (!effectiveBackendOnline) return;
    void refreshGraphSnapshot();
    setStatsRefreshKey((k) => k + 1);
    void backendApi.listDocuments().then((docs) => {
      setDocuments(
        docs.map((d) => ({
          id: d.id,
          title: d.title || d.id.slice(0, 8),
        }))
      );
      if (docs.length === 0) {
        setGraphSnapshot({ nodes: [], links: [] });
        setResult(null);
        setSelectedNodeId(null);
        setPanelEntity(null);
        loadedDocSummariesRef.current.clear();
        loadedTypeKeysRef.current.clear();
        setExpandedDocIds(new Set());
        setExpandedTypeKeys(new Set());
      }
    }).catch(() => {
      setDocuments([]);
      setGraphSnapshot({ nodes: [], links: [] });
      loadedDocSummariesRef.current.clear();
      loadedTypeKeysRef.current.clear();
    });
  }, [effectiveBackendOnline, refreshGraphSnapshot]);

  const handleSearch = useCallback(
    async (query: string, documentId?: string) => {
      if (ingestActive) {
        setSearchError(t("search.blockedDuringIngest"));
        return;
      }
      setLoading(true);
      setHasSearched(true);
      setSearchError(null);
      setLastQuery(query);
      const docFilter = documentId ?? selectedDocumentId;
      try {
        const online = await refreshBackendStatus();
        if (!online) {
          setSearchError(t("search.backendDisconnected"));
          setResult(null);
          return;
        }
        const res = await backendSearch(
          query,
          docFilter || undefined,
          { ...parsedToStructured(parseQuery(query)), ...structuredFilters },
          (partial) => {
            setResult(partial);
            setExpandedDocIds(new Set());
            setGraphFocusDismissed(false);
            setSelectedExpId(null);
            setPanelEntity(null);
            setPanelConnections([]);
            setPanelGroupMembers(undefined);
            setPanelGroupMembersTotal(0);
            setPanelBack(null);
            setSelectedNodeId(null);
          }
        );
        setResult(res);
        if (res.graph.nodes.length > 0) {
          setGraphSnapshot(res.graph);
        }
        setSelectedExpId(res.experiments[0]?.experiment.id ?? null);
      } catch (e) {
        setSearchError(e instanceof Error ? e.message : t("search.failed"));
        setResult(null);
      } finally {
        setLoading(false);
      }
    },
    [ingestActive, refreshBackendStatus, selectedDocumentId, structuredFilters, t]
  );

  const handleDeleteDocument = useCallback(
    async (documentId: string) => {
      try {
        await backendApi.deleteDocument(documentId);
        if (selectedDocumentId === documentId) {
          setSelectedDocumentId("");
        }
        setExpandedDocIds((prev) => {
          if (!prev.has(documentId)) return prev;
          const next = new Set(prev);
          next.delete(documentId);
          return next;
        });
        setPanelEntity((prev) =>
          prev?.type === "article" && prev.id === documentId ? null : prev
        );
        setSearchError(null);
        await refreshAfterIngest();
      } catch (e) {
        setSearchError(e instanceof Error ? e.message : t("documentFilter.deleteFailed"));
        throw e;
      }
    },
    [selectedDocumentId, refreshAfterIngest, t]
  );

  const handleDocumentFilterChange = useCallback(
    (documentId: string) => {
      if (!documentId) {
        setSelectedDocumentId("");
        setExpandedDocIds(new Set());
        setExpandedTypeKeys(new Set());
        return;
      }
      focusDocumentInGraph(documentId);
    },
    [focusDocumentInGraph]
  );

  const handlePickDocument = useCallback(
    (documentId: string) => {
      focusDocumentInGraph(documentId);
      if (lastQuery.trim()) {
        void handleSearch(lastQuery, documentId);
      }
    },
    [lastQuery, handleSearch, focusDocumentInGraph]
  );

  const handleCollapseDocumentGraph = useCallback((documentId: string) => {
    setExpandedDocIds((prev) => {
      if (!prev.has(documentId)) return prev;
      const next = new Set(prev);
      next.delete(documentId);
      return next;
    });
  }, []);

  const handleNodeClick = useCallback(async (node: GraphNode) => {
    const fetchGen = ++panelFetchGenRef.current;

    const applyPanel = (updater: () => void) => {
      if (!mountedRef.current || fetchGen !== panelFetchGenRef.current) return;
      updater();
    };

    setSelectedNodeId(node.id);
    if (node.type === "article") {
      setSelectedDocumentId(node.id);
    }

    if (isTypeClusterNode(node)) {
      const parsed = parseTypeClusterId(node.id);
      setPanelBack(null);
      setPanelEntity(graphNodeToEntity(node));
      setPanelConnections([]);
      setPanelLoading(false);

      if (!parsed) {
        setPanelGroupMembers(undefined);
        setPanelGroupMembersTotal(0);
        setPanelGroupMembersLoading(false);
        return;
      }

      const snapshotMembers = snapshotTypeClusterMembers(
        graphSnapshot.nodes,
        parsed.documentId,
        parsed.entityType
      );
      setPanelGroupMembers(snapshotMembers);
      setPanelGroupMembersTotal(node.typeClusterCount ?? snapshotMembers.length);
      setPanelGroupMembersLoading(true);

      if (typeof window !== "undefined" && window.innerWidth < 1024) {
        requestAnimationFrame(() => {
          panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
      }

      try {
        const { nodes: allMembers, total } = await fetchAllTypeClusterMembers(
          parsed.documentId,
          parsed.entityType
        );
        applyPanel(() => {
          setPanelGroupMembers(allMembers);
          setPanelGroupMembersTotal(total);
        });
      } catch {
        applyPanel(() => {
          setPanelGroupMembers(snapshotMembers);
          setPanelGroupMembersTotal(node.typeClusterCount ?? snapshotMembers.length);
        });
      } finally {
        applyPanel(() => setPanelGroupMembersLoading(false));
      }
      return;
    }

    setPanelGroupMembers(undefined);
    setPanelGroupMembersTotal(0);
    setPanelGroupMembersLoading(false);
    setPanelEntity(graphNodeToEntity(node));
    setPanelConnections([]);
    setPanelLoading(node.type === "article" || node.type === "experiment" || node.type === "property");

    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      requestAnimationFrame(() => {
        panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }

    if (node.type !== "property") {
      void backendApi
        .getNodeNeighbors(node.id)
        .then((graph) => {
          const { nodes, links } = backendGraphToFrontend(graph);
          applyPanel(() => setPanelConnections(getNodeConnections(node.id, nodes, links)));
        })
        .catch(() => {
          applyPanel(() =>
            setPanelConnections(
              getNodeConnections(node.id, graphSnapshot.nodes, graphSnapshot.links)
            )
          );
        });
    }

    if (node.type === "experiment") {
      setSelectedExpId(node.id);
      try {
        const details = await backendApi.getExperiment(node.id);
        applyPanel(() => setPanelEntity(experimentDetailsToEntity(node, details)));
      } catch {
        // Keep graph-node fallback entity
      } finally {
        applyPanel(() => setPanelLoading(false));
      }
      return;
    }

    if (node.type === "property") {
      try {
        const propertyKey = node.id.startsWith("prop:") ? node.id : `prop:${node.id}`;
        const details = await backendApi.getProperty(propertyKey);
        applyPanel(() => setPanelEntity(propertyDetailsToEntity(node, details)));
      } catch {
        // Keep graph-node fallback entity
      } finally {
        applyPanel(() => setPanelLoading(false));
      }
      return;
    }

    if (node.type === "article") {
      try {
        const doc = await backendApi.getDocument(node.id);
        applyPanel(() => setPanelEntity(backendDocumentToArticle(doc, node)));
      } catch {
        // Keep minimal node info if fetch fails
      } finally {
        applyPanel(() => setPanelLoading(false));
      }
      return;
    }

    setPanelLoading(false);
  }, [graphSnapshot.nodes, graphSnapshot.links]);

  const handlePanelBack = useCallback(() => {
    if (!panelBack) return;
    panelFetchGenRef.current += 1;
    setSelectedNodeId(panelBack.selectedNodeId);
    setPanelEntity(panelBack.panelEntity);
    setPanelGroupMembers(panelBack.panelGroupMembers);
    setPanelGroupMembersTotal(panelBack.panelGroupMembersTotal);
    setPanelGroupMembersLoading(panelBack.panelGroupMembersLoading);
    setPanelConnections(panelBack.panelConnections);
    setPanelLoading(panelBack.panelLoading);
    setPanelBack(null);
  }, [panelBack]);

  const handleGroupMemberClick = useCallback(
    (nodeId: string) => {
      if (panelGroupMembers !== undefined && panelEntity) {
        setPanelBack({
          selectedNodeId: panelEntity.id,
          panelEntity,
          panelGroupMembers,
          panelGroupMembersTotal,
          panelGroupMembersLoading,
          panelConnections,
          panelLoading,
        });
      }
      const member =
        graphSnapshot.nodes.find((n) => n.id === nodeId) ??
        panelGroupMembers?.find((n) => n.id === nodeId);
      if (!member) return;

      const hubId = member.hubId ?? member.documentId;
      if (hubId) {
        setExpandedDocIds((prev) => {
          if (prev.has(hubId)) return prev;
          const next = new Set(prev);
          next.add(hubId);
          return next;
        });
        if (!loadedDocSummariesRef.current.has(hubId)) {
          void loadDocumentSubgraph(hubId);
        }
      }

      const typeKey = hubId ? expandedTypeKey(hubId, member.type) : null;
      if (typeKey) {
        setExpandedTypeKeys((prev) => {
          if (prev.has(typeKey)) return prev;
          const next = new Set(prev);
          next.add(typeKey);
          return next;
        });
        if (hubId && !loadedTypeKeysRef.current.has(typeKey)) {
          void loadTypeClusterEntities(hubId, member.type);
        }
      }

      if (!graphSnapshot.nodes.some((n) => n.id === nodeId)) {
        setGraphSnapshot((prev) =>
          mergeGraphSnapshots(prev, {
            nodes: [
              {
                ...member,
                hubId: hubId ?? member.hubId,
                documentId: hubId ?? member.documentId,
              },
            ],
            links: [],
          })
        );
      }

      setSelectedNodeId(nodeId);
      void handleNodeClick(member);
    },
    [
      graphSnapshot.nodes,
      handleNodeClick,
      loadDocumentSubgraph,
      loadTypeClusterEntities,
      panelConnections,
      panelEntity,
      panelGroupMembers,
      panelGroupMembersLoading,
      panelGroupMembersTotal,
      panelLoading,
    ]
  );

  const handleConnectionClick = useCallback(
    (nodeId: string) => {
      const node =
        graphSnapshot.nodes.find((n) => n.id === nodeId) ??
        panelGroupMembers?.find((n) => n.id === nodeId);
      if (node) void handleNodeClick(node);
    },
    [graphSnapshot.nodes, panelGroupMembers, handleNodeClick]
  );

  const handleExpClick = useCallback(
    (expId: string) => {
      setSelectedExpId(expId);
      const expResult = result?.experiments.find((r) => r.experiment.id === expId);
      if (expResult) {
        setPanelEntity(expResult.experiment);
      }
    },
    [result]
  );

  const displayGraph = graphSnapshot;

  const graphEmptyMessage =
    graphSnapshot.nodes.length === 0
      ? graphLoading
        ? t("graph.emptyLoading")
        : !effectiveBackendOnline
          ? t("graph.emptyOffline")
          : !hasSearched
            ? t("graph.emptyNoData")
            : t("graph.emptyNoData")
      : undefined;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-800/80 bg-slate-950/80 px-6 py-5 backdrop-blur">
        <div className="mx-auto max-w-[1600px]">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500 to-violet-600 shadow-lg shadow-cyan-500/20">
                <Network className="h-5 w-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-slate-100">
                  {t("header.title")}
                </h1>
                <p className="text-sm text-slate-500">{t("header.subtitle")}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <ModelSwitcher />
              <LanguageSwitcher />
              <div
              className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
                backendOnline
                  ? "border-emerald-500/30 text-emerald-400"
                  : ingestActive
                    ? "border-cyan-500/30 text-cyan-400"
                    : "border-amber-500/30 text-amber-400"
              }`}
            >
              {backendOnline ? (
                <>
                  <Server className="h-3.5 w-3.5" />
                  {t("header.backendConnected")}
                </>
              ) : ingestActive ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t("header.backendProcessing")}
                </>
              ) : (
                <>
                  <ServerOff className="h-3.5 w-3.5" />
                  {t("header.backendOffline")}
                </>
              )}
            </div>
            </div>
          </div>

          {ingestActive && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-cyan-500/30 bg-cyan-950/20 px-4 py-3 text-sm text-cyan-100">
              <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
              <p>{t("search.blockedDuringIngest")}</p>
            </div>
          )}

          {!effectiveBackendOnline && !ingestActive && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{t("header.backendHint")}</p>
            </div>
          )}

          <div className="mb-3">
            <DocumentFilter
              documents={documents}
              value={selectedDocumentId}
              onChange={handleDocumentFilterChange}
              onDelete={effectiveBackendOnline ? handleDeleteDocument : undefined}
              disabled={!effectiveBackendOnline}
              loading={loading}
            />
          </div>

          <SearchBar
            onSearch={handleSearch}
            loading={loading}
            disabled={searchBlocked}
            placeholder={ingestActive ? t("search.placeholderIngest") : undefined}
          />

          <div className="mt-3">
            <QueryFilters
              value={structuredFilters}
              onChange={setStructuredFilters}
              disabled={!effectiveBackendOnline || loading}
            />
          </div>

          {searchError && (
            <p className="mt-2 text-sm text-red-400">{searchError}</p>
          )}

          {result?.needsDisambiguation && result.documentCandidates && (
            <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-100">
              <p className="mb-2 font-medium">{t("search.disambiguation")}</p>
              <div className="flex flex-wrap gap-2">
                {result.documentCandidates.map((candidate) => (
                  <button
                    key={candidate.documentId}
                    type="button"
                    onClick={() => handlePickDocument(candidate.documentId)}
                    className="rounded-lg border border-amber-500/40 bg-amber-900/30 px-3 py-1.5 text-xs hover:bg-amber-800/40"
                  >
                    {candidate.title || candidate.documentId.slice(0, 8)}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="mt-4">
            <StatsBar
              useBackend={effectiveBackendOnline}
              refreshKey={statsRefreshKey}
              activeFilter={graphTypeFilter}
              onFilterChange={setGraphTypeFilter}
            />
          </div>
          <div className="mt-4">
            <DocumentUpload
              disabled={!effectiveBackendOnline}
              onIngestComplete={() => {
                void refreshAfterIngest();
              }}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-4 p-6 lg:flex-row">
        <section className="flex min-w-0 flex-1 flex-col gap-4">
          {result?.narrative && (
            <div className="flex items-start gap-3 rounded-xl border border-cyan-500/20 bg-cyan-950/20 p-4">
              <MessageSquareQuote className="mt-0.5 h-5 w-5 shrink-0 text-cyan-400" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="flex-1 text-sm leading-relaxed text-slate-200 whitespace-pre-wrap">
                    {result.narrative}
                  </p>
                  <div className="flex shrink-0 flex-wrap gap-1">
                    {result.confidence != null && result.confidence > 0 && (
                      <span className="rounded-full bg-cyan-500/15 px-2.5 py-0.5 text-xs font-medium text-cyan-300">
                        {t("narrative.confidence", {
                          pct: Math.round(result.confidence * 100),
                        })}
                      </span>
                    )}
                    {result.retrievalScope?.mode === "structured_filters" && (
                      <span className="rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs font-medium text-emerald-300">
                        {t("narrative.scopedStructured", {
                          count:
                            result.retrievalScope.graphMatchCount ??
                            result.retrievalScope.filterDocumentIds?.length ??
                            0,
                        })}
                      </span>
                    )}
                    {result.retrievalScope?.mode === "structured_fallback" && (
                      <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-xs font-medium text-amber-300">
                        {t("narrative.fallbackStructured")}
                      </span>
                    )}
                    {result.retrievalScope?.mode === "explicit_document" && (
                      <span className="rounded-full bg-violet-500/15 px-2.5 py-0.5 text-xs font-medium text-violet-300">
                        {t("narrative.scopedDocument")}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        downloadText(
                          "rd-query-report.md",
                          exportSearchMarkdown(result),
                          "text/markdown"
                        )
                      }
                      className="flex items-center gap-1 rounded-full border border-slate-600 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
                    >
                      <Download className="h-3 w-3" /> MD
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        downloadText("rd-query-report.json", exportSearchJson(result))
                      }
                      className="flex items-center gap-1 rounded-full border border-slate-600 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
                    >
                      <Download className="h-3 w-3" /> JSON
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        void backendApi.exportJsonLd().then((ld) =>
                          downloadText(
                            "knowledge-map.jsonld",
                            JSON.stringify(ld, null, 2),
                            "application/ld+json"
                          )
                        )
                      }
                      className="flex items-center gap-1 rounded-full border border-slate-600 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
                    >
                      <Download className="h-3 w-3" /> JSON-LD
                    </button>
                  </div>
                </div>
                {(result.parsed.material || result.parsed.mode || result.parsed.property) && (
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    {result.parsed.material && (
                      <span className="rounded bg-pink-500/10 px-2 py-0.5 text-pink-300">
                        {result.parsed.material}
                      </span>
                    )}
                    {result.parsed.mode && (
                      <span className="rounded bg-violet-500/10 px-2 py-0.5 text-violet-300">
                        {result.parsed.mode}
                      </span>
                    )}
                    {result.parsed.property && (
                      <span className="rounded bg-amber-500/10 px-2 py-0.5 text-amber-300">
                        {result.parsed.property}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {result?.sources && result.sources.length > 0 && (
            <SourceExcerpts sources={result.sources} />
          )}

            <GraphView
              containerRef={graphRef}
              nodes={displayGraph.nodes}
              links={displayGraph.links}
              onNodeClick={handleNodeClick}
              onDocumentExpand={loadDocumentSubgraph}
              onTypeClusterExpand={loadTypeClusterEntities}
              onDocumentCollapse={handleDocumentCollapse}
              highlightId={selectedDocumentId || selectedNodeId || selectedExpId || undefined}
              emptyMessage={graphEmptyMessage}
              typeFilter={graphTypeFilter}
              selectedDocumentId={selectedDocumentId || undefined}
              expandingDocId={expandingDocId}
              expandingTypeKey={expandingTypeKey}
              expandedDocIds={expandedDocIds}
              onExpandedDocIdsChange={setExpandedDocIds}
              expandedTypeKeys={expandedTypeKeys}
              onExpandedTypeKeysChange={setExpandedTypeKeys}
              searchFocus={graphFocusDismissed ? null : searchFocus}
              onDismissSearchFocus={() => setGraphFocusDismissed(true)}
            />
        </section>

        <aside className="flex w-full flex-col gap-4 lg:w-[400px] lg:shrink-0">
          <div
            ref={panelRef}
            className={
              panelEntity || graphTypeFilter
                ? "h-[320px] lg:h-auto lg:min-h-[200px]"
                : "hidden lg:block lg:min-h-0"
            }
          >
            {panelEntity ? (
              <EntityPanel
                entity={panelEntity}
                loading={panelLoading}
                connections={panelConnections}
                groupMembers={panelGroupMembers}
                groupMembersTotal={panelGroupMembersTotal}
                groupMembersLoading={panelGroupMembersLoading}
                onConnectionClick={handleConnectionClick}
                onGroupMemberClick={handleGroupMemberClick}
                onBack={panelBack ? handlePanelBack : undefined}
                backLabel={
                  panelBack
                    ? t("entityPanel.backToGroup", { name: panelBack.panelEntity.name })
                    : undefined
                }
                documentGraphExpanded={
                  panelEntity.type === "article" && expandedDocIds.has(panelEntity.id)
                }
                onCollapseDocumentGraph={
                  panelEntity.type === "article"
                    ? () => handleCollapseDocumentGraph(panelEntity.id)
                    : undefined
                }
                onClose={() => {
                  setPanelEntity(null);
                  setPanelConnections([]);
                  setPanelGroupMembers(undefined);
                  setPanelGroupMembersTotal(0);
                  setPanelGroupMembersLoading(false);
                  setPanelBack(null);
                  setSelectedNodeId(null);
                }}
              />
            ) : graphTypeFilter ? (
              <EntityBrowsePanel
                entityType={graphTypeFilter}
                onClose={() => setGraphTypeFilter(null)}
                onSelectNode={(node) => {
                  void handleNodeClick(node);
                }}
              />
            ) : (
              <div className="hidden rounded-xl border border-dashed border-slate-700/50 bg-slate-900/30 p-6 text-center text-sm text-slate-500 lg:block">
                {t("graph.clickHint")}
              </div>
            )}
          </div>

          {result && result.experiments.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-medium text-slate-300">
                {t("experiments.title", { count: result.experiments.length })}
              </h2>
              <div className="max-h-[340px] space-y-2 overflow-y-auto pr-1">
                {result.experiments.map((r) => (
                  <ExperimentCard
                    key={r.experiment.id}
                    result={r}
                    selected={selectedExpId === r.experiment.id}
                    onClick={() => handleExpClick(r.experiment.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {result && <Timeline experiments={result.experiments} />}

          <ContradictionsPanel enabled={effectiveBackendOnline} />
        </aside>
      </main>
    </div>
  );
}
