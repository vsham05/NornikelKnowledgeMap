"use client";

import type { Entity, Experiment, Article, Material, Team, Facility } from "@/lib/types";
import { getEntityLabel, getEntityColor } from "@/lib/graph";
import { relationLabel } from "@/lib/adapters/backend";
import type { NodeConnection } from "@/lib/graphConnections";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { X, FileText, ExternalLink } from "lucide-react";

interface EntityPanelProps {
  entity: Entity | null;
  loading?: boolean;
  connections?: NodeConnection[];
  onConnectionClick?: (nodeId: string) => void;
  onClose: () => void;
}

function asMaterial(entity: Entity): Material | null {
  if (entity.type !== "material") return null;
  return entity as Material;
}

export function EntityPanel({
  entity,
  loading,
  connections,
  onConnectionClick,
  onClose,
}: EntityPanelProps) {
  const { t, locale } = useI18n();
  if (!entity) return null;

  const isArticle = entity.type === "article";
  const isExperiment = entity.type === "experiment";
  const isMaterial = entity.type === "material";
  const isTeam = entity.type === "team";
  const isFacility = entity.type === "facility";
  const article = entity.type === "article" ? (entity as Partial<Article>) : null;
  const material = asMaterial(entity);
  const team = isTeam ? (entity as Team) : null;
  const facility = isFacility ? (entity as Facility) : null;
  const exp = isExperiment ? (entity as Experiment) : null;

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-700/60 bg-slate-900/90 backdrop-blur">
      <div className="flex items-center justify-between border-b border-slate-700/60 p-4">
        <div className="flex items-center gap-2">
          <span
            className="rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white"
            style={{ backgroundColor: getEntityColor(entity.type) }}
          >
            {getEntityLabel(entity.type, locale)}
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
          <p className="mt-2 text-xs text-slate-500">{t("entityPanel.loading")}</p>
        )}
        {"description" in entity && entity.description && (
          <p className="mt-2 break-all text-sm text-slate-400">{entity.description}</p>
        )}

        {connections !== undefined && (
          <div className="mt-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("entityPanel.connections", { count: connections.length })}
            </div>
            {connections.length === 0 ? (
              <p className="mt-2 text-xs text-slate-500">{t("entityPanel.noConnections")}</p>
            ) : (
              <ul className="mt-2 max-h-[280px] space-y-1.5 overflow-y-auto pr-1">
                {connections.map((conn) => (
                  <li key={`${conn.node.id}-${conn.relation}-${conn.direction}`}>
                    <button
                      type="button"
                      onClick={() => onConnectionClick?.(conn.node.id)}
                      className="w-full rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-left transition hover:border-slate-600 hover:bg-slate-800/70"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-white"
                          style={{ backgroundColor: getEntityColor(conn.node.type) }}
                        >
                          {getEntityLabel(conn.node.type, locale)}
                        </span>
                        <span className="truncate text-sm text-slate-200">
                          {conn.node.name}
                        </span>
                      </div>
                      <div className="mt-0.5 text-[10px] text-slate-500">
                        {relationLabel(conn.relation, locale)}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
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
                {t("entityPanel.authors")}: {article.authors.join(", ")}
              </p>
            )}
            {article.textLayer && (
              <div>
                <div className="mb-1 flex items-center gap-1 text-xs font-medium text-slate-500">
                  <FileText className="h-3 w-3" />
                  {t("entityPanel.summary")}
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
                {t("entityPanel.openSource")}
              </a>
            )}
            {!article.url && !article.textLayer && !loading && (
              null
            )}
          </div>
        )}

        {isArticle && !article?.textLayer && !loading && !article?.authors?.length && !article?.url && (
          <p className="mt-3 text-xs text-slate-500">
            {t("entityPanel.documentNode")}
          </p>
        )}

        {exp && (
          <div className="mt-4 space-y-3">
            <div className="font-mono text-xs text-slate-500">{exp.code}</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-slate-800/50 p-2">
                <div className="text-slate-500">{t("entityPanel.status")}</div>
                <div className="mt-0.5 capitalize text-slate-200">{exp.status}</div>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2">
                <div className="text-slate-500">{t("entityPanel.started")}</div>
                <div className="mt-0.5 text-slate-200">{exp.startedAt}</div>
              </div>
            </div>
            {exp.measurements.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-slate-500">{t("entityPanel.measurements")}</div>
                <div className="space-y-2">
                  {exp.measurements.map((m, i) => (
                    <div key={i} className="rounded-lg bg-slate-800/50 p-2 text-xs">
                      <div className="text-slate-300">
                        {m.before !== undefined && m.after !== undefined
                          ? `${m.before} → ${m.after} ${m.unit}`
                          : t("entityPanel.recordedIn", { unit: m.unit })}
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

        {isMaterial && material && (
          <div className="mt-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("entityPanel.materialsGroup", {
                count: material.components?.length ?? 1,
              })}
            </div>
            <ul className="mt-2 space-y-1.5">
              {(material.components?.length ? material.components : [material.name]).map(
                (item) => (
                  <li
                    key={item}
                    className="rounded-lg border border-pink-500/20 bg-pink-950/25 px-3 py-2 text-sm text-pink-100"
                  >
                    {item}
                  </li>
                )
              )}
            </ul>
          </div>
        )}

        {isTeam && team && (
          <div className="mt-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("entityPanel.researchTeam")}
            </div>
            {team.members && team.members.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {team.members.map((member) => (
                  <li
                    key={member}
                    className="rounded-lg border border-orange-500/20 bg-orange-950/25 px-3 py-2 text-sm text-orange-100"
                  >
                    {member}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}

        {isFacility && facility && (
          <div className="mt-4 space-y-2">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("entityPanel.siteDetails")}
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {facility.facilityType && (
                <div className="rounded-lg bg-violet-950/30 p-2">
                  <div className="text-slate-500">{t("entityPanel.type")}</div>
                  <div className="mt-0.5 capitalize text-violet-100">
                    {facility.facilityType}
                  </div>
                </div>
              )}
              {facility.country && (
                <div className="rounded-lg bg-violet-950/30 p-2">
                  <div className="text-slate-500">{t("entityPanel.country")}</div>
                  <div className="mt-0.5 text-violet-100">{facility.country}</div>
                </div>
              )}
            </div>
          </div>
        )}

        {!isArticle && !isExperiment && !isMaterial && !isTeam && !isFacility && (
          null
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
