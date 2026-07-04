import type { LlmProvider } from "@/lib/api/backend";

export const INGEST_ROUTE_EVENT = "ingest-llm-route";
export const INGEST_START_EVENT = "ingest-start";
export const INGEST_COMPLETE_EVENT = "ingest-complete";

export type IngestRouteDetail = {
  provider: LlmProvider;
  model?: string;
};

export function dispatchIngestRoute(detail: IngestRouteDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<IngestRouteDetail>(INGEST_ROUTE_EVENT, { detail }));
}

export function dispatchIngestStart() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(INGEST_START_EVENT));
}

export function dispatchIngestComplete() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(INGEST_COMPLETE_EVENT));
}
