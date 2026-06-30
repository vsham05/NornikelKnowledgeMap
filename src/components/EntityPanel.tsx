import type { Entity, Experiment, Article } from "@/lib/types";
import { getEntityLabel, getEntityColor } from "@/lib/graph";
import { X, FileText, ExternalLink } from "lucide-react";

interface EntityPanelProps {
  entity: Entity | null;
  loading?: boolean;
  onClose: () => void;
}

function asArticle(entity: Entity): Partial<Article> | null {
  if (entity.type !== "article") return null;
  return entity as Partial<Article>;
}

export function EntityPanel({ entity, loading, onClose }: EntityPanelProps) {
  if (!entity) return null;

  const isArticle = entity.type === "article";
  const isExperiment = entity.type === "experiment";
  const article = asArticle(entity);
  const exp = isExperiment ? (entity as Experiment) : null;

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-700/60 bg-slate-900/90 backdrop-blur">
      <div className="flex items-center justify-between border-b border-slate-700/60 p-4">
        <div className="flex items-center gap-2">
          <span
            className="rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white"
            style={{ backgroundColor: getEntityColor(entity.type) }}
          >
            {getEntityLabel(entity.type)}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <h3 className="text-lg font-semibold text-slate-100">{entity.name}</h3>
        {loading && (
          <p className="mt-2 text-xs text-slate-500">Loading document details…</p>
        )}
        {"description" in entity && entity.description && (
          <p className="mt-2 break-all text-sm text-slate-400">{entity.description}</p>
        )}

        {isArticle && article && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              {article.format && (
                <span className="rounded bg-slate-800 px-2 py-1 text-slate-300">
                  {article.format.toUpperCase()}
                </span>
              )}
              {article.source && (
                <span className="rounded bg-slate-800 px-2 py-1 text-slate-300">
                  {article.source}
                </span>
              )}
              {article.publishedAt && article.publishedAt !== "—" && (
                <span className="rounded bg-slate-800 px-2 py-1 text-slate-300">
                  {article.publishedAt}
                </span>
              )}
            </div>
            {article.authors && article.authors.length > 0 && (
              <p className="text-xs text-slate-500">
                Authors: {article.authors.join(", ")}
              </p>
            )}
            {article.textLayer && (
              <div>
                <div className="mb-1 flex items-center gap-1 text-xs font-medium text-slate-500">
                  <FileText className="h-3 w-3" />
                  Summary
                </div>
                <p className="rounded-lg bg-slate-800/50 p-3 text-sm leading-relaxed text-slate-300">
                  {article.textLayer}
                </p>
              </div>
            )}
            {article.url && (
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-cyan-400 hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                Open source
              </a>
            )}
            {!article.url && !article.textLayer && !loading && (
              <p className="text-xs text-slate-500">
                Click a search result to view source excerpts, or re-open after the document loads.
              </p>
            )}
          </div>
        )}

        {isArticle && !article?.textLayer && !loading && (
          <p className="mt-3 text-xs text-slate-500">
            This node is an ingested document in your knowledge graph.
          </p>
        )}

        {exp && (
          <div className="mt-4 space-y-3">
            <div className="font-mono text-xs text-slate-500">{exp.code}</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-slate-800/50 p-2">
                <div className="text-slate-500">Status</div>
                <div className="mt-0.5 capitalize text-slate-200">{exp.status}</div>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2">
                <div className="text-slate-500">Started</div>
                <div className="mt-0.5 text-slate-200">{exp.startedAt}</div>
              </div>
            </div>
            {exp.measurements.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-slate-500">Measurements</div>
                <div className="space-y-2">
                  {exp.measurements.map((m, i) => (
                    <div key={i} className="rounded-lg bg-slate-800/50 p-2 text-xs">
                      <div className="text-slate-300">
                        {m.before !== undefined && m.after !== undefined
                          ? `${m.before} → ${m.after} ${m.unit}`
                          : `Recorded in ${m.unit}`}
                      </div>
                      {m.changePercent !== undefined && (
                        <div
                          className={
                            m.changePercent > 0 ? "text-emerald-400" : "text-red-400"
                          }
                        >
                          {m.changePercent > 0 ? "+" : ""}
                          {m.changePercent.toFixed(1)}%
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!isArticle && !isExperiment && (
          <p className="mt-3 text-sm text-slate-400">
            Graph entity from your Neo4j knowledge base.
          </p>
        )}

        {"tags" in entity && entity.tags && entity.tags.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1">
            {entity.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400"
              >
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
