"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { SearchBar } from "@/components/SearchBar";
import { GraphView } from "@/components/GraphView";
import { ExperimentCard } from "@/components/ExperimentCard";
import { GapAnalysis } from "@/components/GapAnalysis";
import { Timeline } from "@/components/Timeline";
import { EntityPanel } from "@/components/EntityPanel";
import { StatsBar } from "@/components/StatsBar";
import { DocumentUpload } from "@/components/DocumentUpload";
import { DocumentFilter, type DocumentOption } from "@/components/DocumentFilter";
import { SourceExcerpts } from "@/components/SourceExcerpts";
import { checkBackendHealth, backendApi } from "@/lib/api/backend";
import { backendSearch, backendGraphToFrontend } from "@/lib/adapters/backend";
import { backendDocumentToArticle, graphNodeToEntity } from "@/lib/entityFromGraph";
import { QueryFilters } from "@/components/QueryFilters";
import { CoverageMatrix } from "@/components/CoverageMatrix";
import { ContradictionsPanel } from "@/components/ContradictionsPanel";
import { downloadText, exportSearchJson, exportSearchMarkdown } from "@/lib/exportResults";
import { parseQuery, parsedToStructured } from "@/lib/query";
import type { Entity, GraphEdge, GraphNode, SearchResult, EntityType, StructuredFilters } from "@/lib/types";
import { Network, MessageSquareQuote, Server, ServerOff, AlertCircle, Download } from "lucide-react";

export function Dashboard() {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedExpId, setSelectedExpId] = useState<string | null>(null);
  const [panelEntity, setPanelEntity] = useState<Entity | null>(null);
  const [panelLoading, setPanelLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [statsRefreshKey, setStatsRefreshKey] = useState(0);
  const [graphSnapshot, setGraphSnapshot] = useState<{
    nodes: GraphNode[];
    links: GraphEdge[];
  }>({ nodes: [], links: [] });
  const [graphVersion, setGraphVersion] = useState(0);
  const [graphTypeFilter, setGraphTypeFilter] = useState<EntityType | null>(null);
  const [documents, setDocuments] = useState<DocumentOption[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [structuredFilters, setStructuredFilters] = useState<StructuredFilters>({});
  const panelRef = useRef<HTMLDivElement>(null);

  const refreshBackendStatus = useCallback(async () => {
    const ok = await checkBackendHealth();
    setBackendOnline(ok);
    return ok;
  }, []);

  const refreshGraphSnapshot = useCallback(async () => {
    const explore = await backendApi.exploreGraph(300).catch(() => null);
    if (!explore) return;

    const graph = backendGraphToFrontend(explore);
    setGraphSnapshot(graph);
    setGraphVersion((v) => v + 1);
    setResult((prev) => (prev ? { ...prev, graph } : prev));
  }, []);

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
    if (backendOnline) {
      void refreshGraphSnapshot();
      setStatsRefreshKey((k) => k + 1);
      void backendApi.listDocuments().then((docs) => {
        setDocuments(
          docs.map((d) => ({
            id: d.id,
            title: d.title || d.id.slice(0, 8),
          }))
        );
      }).catch(() => setDocuments([]));
    }
  }, [backendOnline, refreshGraphSnapshot]);

  const handleSearch = useCallback(
    async (query: string, documentId?: string) => {
      setLoading(true);
      setHasSearched(true);
      setSearchError(null);
      setLastQuery(query);
      const docFilter = documentId ?? selectedDocumentId;
      try {
        const online = await refreshBackendStatus();
        if (!online) {
          setSearchError("Backend is not connected. Start Docker and the FastAPI server.");
          setResult(null);
          return;
        }
        const res = await backendSearch(
          query,
          docFilter || undefined,
          { ...parsedToStructured(parseQuery(query)), ...structuredFilters }
        );
        setResult(res);
        if (res.graph.nodes.length > 0) {
          setGraphSnapshot(res.graph);
          setGraphVersion((v) => v + 1);
        }
        setSelectedExpId(res.experiments[0]?.experiment.id ?? null);
        setPanelEntity(null);
        setSelectedNodeId(null);
      } catch (e) {
        setSearchError(e instanceof Error ? e.message : "Search failed");
        setResult(null);
      } finally {
        setLoading(false);
      }
    },
    [refreshBackendStatus, selectedDocumentId, structuredFilters]
  );

  const handlePickDocument = useCallback(
    (documentId: string) => {
      setSelectedDocumentId(documentId);
      if (lastQuery.trim()) {
        void handleSearch(lastQuery, documentId);
      }
    },
    [lastQuery, handleSearch]
  );

  const handleNodeClick = useCallback(async (node: GraphNode) => {
    setSelectedNodeId(node.id);
    setPanelEntity(graphNodeToEntity(node));
    setPanelLoading(node.type === "article");

    requestAnimationFrame(() => {
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });

    if (node.type === "experiment") {
      setSelectedExpId(node.id);
      setPanelLoading(false);
      return;
    }

    if (node.type === "article") {
      try {
        const doc = await backendApi.getDocument(node.id);
        setPanelEntity(backendDocumentToArticle(doc, node));
      } catch {
        // Keep minimal node info if fetch fails
      } finally {
        setPanelLoading(false);
      }
      return;
    }

    setPanelLoading(false);
  }, []);

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
    displayGraph.nodes.length === 0
      ? !backendOnline
        ? "Connect the backend to load the knowledge graph."
        : !hasSearched
          ? "Loading graph from Neo4j… upload documents or wait a moment."
          : "No graph data yet. Upload PDFs or DOCX files to build the knowledge graph."
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
                  R&D Knowledge Map
                </h1>
                <p className="text-sm text-slate-500">
                  Mining & metallurgy · Neo4j graph · Qdrant RAG · provenance & geography
                </p>
              </div>
            </div>
            <div
              className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
                backendOnline
                  ? "border-emerald-500/30 text-emerald-400"
                  : "border-amber-500/30 text-amber-400"
              }`}
            >
              {backendOnline ? (
                <>
                  <Server className="h-3.5 w-3.5" />
                  Backend connected
                </>
              ) : (
                <>
                  <ServerOff className="h-3.5 w-3.5" />
                  Backend offline
                </>
              )}
            </div>
          </div>

          {!backendOnline && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                Start Docker (<code className="text-amber-100">docker compose up -d</code>) and the
                FastAPI backend (<code className="text-amber-100">start-backend.bat</code>) to search
                and ingest documents.
              </p>
            </div>
          )}

          <div className="mb-3">
            <DocumentFilter
              documents={documents}
              value={selectedDocumentId}
              onChange={setSelectedDocumentId}
              disabled={!backendOnline}
              loading={loading}
            />
          </div>

          <div className="mb-3">
            <QueryFilters
              value={structuredFilters}
              onChange={setStructuredFilters}
              disabled={!backendOnline || loading}
            />
          </div>

          <SearchBar onSearch={handleSearch} loading={loading} disabled={!backendOnline} />
          {searchError && (
            <p className="mt-2 text-sm text-red-400">{searchError}</p>
          )}

          {result?.needsDisambiguation && result.documentCandidates && (
            <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-100">
              <p className="mb-2 font-medium">Multiple documents match — pick one:</p>
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
              useBackend={backendOnline}
              refreshKey={statsRefreshKey}
              activeFilter={graphTypeFilter}
              onFilterChange={setGraphTypeFilter}
            />
          </div>
          <div className="mt-4">
            <DocumentUpload
              disabled={!backendOnline}
              onIngestComplete={() => {
                void refreshAfterIngest();
              }}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-4 p-6 lg:flex-row">
        <section className="flex min-h-[420px] flex-1 flex-col gap-4 lg:min-h-0">
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
                        confidence: {Math.round(result.confidence * 100)}%
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

          <div className="min-h-[360px] flex-1">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs text-slate-500">
                Knowledge graph — documents, experiments, materials, modes & teams linked by source
              </p>
              {displayGraph.nodes.length > 0 && (
                <span className="shrink-0 text-[10px] text-slate-600">
                  {displayGraph.nodes.length} nodes · {displayGraph.links.length} links
                </span>
              )}
            </div>
            <GraphView
              key={graphVersion}
              nodes={displayGraph.nodes}
              links={displayGraph.links}
              onNodeClick={handleNodeClick}
              highlightId={selectedNodeId ?? selectedExpId ?? undefined}
              emptyMessage={graphEmptyMessage}
              typeFilter={graphTypeFilter}
            />
          </div>
        </section>

        <aside className="flex w-full flex-col gap-4 lg:w-[400px] lg:shrink-0">
          <div
            ref={panelRef}
            className={
              panelEntity
                ? "h-[320px] lg:h-auto lg:min-h-[200px]"
                : "hidden lg:block lg:min-h-0"
            }
          >
            {panelEntity ? (
              <EntityPanel
                entity={panelEntity}
                loading={panelLoading}
                onClose={() => {
                  setPanelEntity(null);
                  setSelectedNodeId(null);
                }}
              />
            ) : (
              <div className="hidden rounded-xl border border-dashed border-slate-700/50 bg-slate-900/30 p-6 text-center text-sm text-slate-500 lg:block">
                Click a graph node to view document or entity details.
              </div>
            )}
          </div>

          {result && result.experiments.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-medium text-slate-300">
                Experiments ({result.experiments.length})
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

          <CoverageMatrix enabled={backendOnline} />
          <ContradictionsPanel enabled={backendOnline} />

          {result && (
            <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
              <GapAnalysis gaps={result.gaps} />
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
