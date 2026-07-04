"use client";

import type { Entity, Experiment, Article, Material, Team, Facility, Figures, Property } from "@/lib/types";
import { getEntityLabel, getEntityColor } from "@/lib/graph";
import { relationLabel } from "@/lib/adapters/backend";
import { figureImageUrl } from "@/lib/api/backend";
import type { NodeConnection } from "@/lib/graphConnections";
import type { GraphNode } from "@/lib/types";
import { PropertyMeasurementsList } from "@/components/PropertyMeasurementsList";
import { SearchableEntityList } from "@/components/SearchableEntityList";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { X, FileText, ExternalLink, Minimize2, ArrowLeft } from "lucide-react";

interface EntityPanelProps {
  entity: Entity | null;
  loading?: boolean;
  connections?: NodeConnection[];
  groupMembers?: GraphNode[];
  groupMembersTotal?: number;
  groupMembersLoading?: boolean;
  onConnectionClick?: (nodeId: string) => void;
  onGroupMemberClick?: (nodeId: string) => void;
  onBack?: () => void;
  backLabel?: string;
  onClose: () => void;
  documentGraphExpanded?: boolean;
  onCollapseDocumentGraph?: () => void;
}

function asMaterial(entity: Entity): Material | null {
  if (entity.type !== "material") return null;
  return entity as Material;
}

export function EntityPanel({
  entity,
  loading,
  connections,
  groupMembers,
  groupMembersTotal,
  groupMembersLoading,
  onConnectionClick,
  onGroupMemberClick,
  onBack,
  backLabel,
  onClose,
  documentGraphExpanded,
  onCollapseDocumentGraph,
}: EntityPanelProps) {
  const { t, locale } = useI18n();
  if (!entity) return null;

  const isArticle = entity.type === "article";
  const isExperiment = entity.type === "experiment";
  const isMaterial = entity.type === "material";
  const isTeam = entity.type === "team";
  const isFacility = entity.type === "facility";
  const isFigures = entity.type === "figures";
  const isProperty = entity.type === "property";
  const article = entity.type === "article" ? (entity as Partial<Article>) : null;
  const material = asMaterial(entity);
  const team = isTeam ? (entity as Team) : null;
  const facility = isFacility ? (entity as Facility) : null;
  const figures = isFigures ? (entity as Figures) : null;
  const property = isProperty ? (entity as Property) : null;
  const exp = isExperiment ? (entity as Experiment) : null;
  const showGroupMembers = groupMembers !== undefined;
  const memberCount = groupMembersTotal ?? groupMembers?.length ?? 0;

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-700/60 bg-slate-900/90 backdrop-blur">
      <div className="flex items-center justify-between gap-2 border-b border-slate-700/60 p-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-600/70 bg-slate-800/60 px-2 py-1 text-xs text-slate-300 transition hover:border-slate-500 hover:bg-slate-800 hover:text-slate-100"
              title={backLabel}
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span className="max-w-[8rem] truncate">
                {backLabel ?? t("entityPanel.backToGroup", { name: "…" })}
              </span>
            </button>
          )}
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

        {showGroupMembers && (
          <div className="mt-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("entityPanel.groupMembers", { count: memberCount })}
            </div>
            <SearchableEntityList
              items={(groupMembers ?? []).map((member) => ({
                id: member.id,
                name: member.name,
                type: member.type,
              }))}
              total={memberCount}
              loading={groupMembersLoading}
              emptyLabel={t("entityPanel.noGroupMembers")}
              onItemClick={onGroupMemberClick}
            />
          </div>
        )}

        {connections !== undefined && !isProperty && !showGroupMembers && (
          <div className="mt-4">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("entityPanel.connections", { count: connections.length })}
              </div>
              {isArticle &&
                documentGraphExpanded &&
                onCollapseDocumentGraph &&
                connections.length > 0 && (
                  <button
                    type="button"
                    onClick={onCollapseDocumentGraph}
                    className="flex shrink-0 items-center gap-1 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-[10px] font-medium text-cyan-300 transition hover:border-cyan-400/60 hover:bg-cyan-500/20"
                    title={t("entityPanel.collapseGraphHint")}
                  >
                    <Minimize2 className="h-3 w-3" />
                    {t("entityPanel.collapseGraph")}
                  </button>
                )}
            </div>
            <SearchableEntityList
              items={connections.map((conn) => ({
                id: conn.node.id,
                name: conn.node.name,
                type: conn.node.type,
                subtitle: relationLabel(conn.relation, locale),
              }))}
              total={connections.length}
              emptyLabel={t("entityPanel.noConnections")}
              onItemClick={onConnectionClick}
              maxHeightClass="max-h-[280px]"
            />
          </div>
        )}

        {isFigures && figures && (
          <div className="mt-4">
            {figures.typeSummary && (
              <p className="text-xs text-slate-500">{figures.typeSummary}</p>
            )}
            <div className="mt-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("entityPanel.figuresList", {
                count: figures.items.length,
              })}
            </div>
            <ul className="mt-2 max-h-[360px] space-y-2 overflow-y-auto pr-1">
              {figures.items.map((fig) => (
                <li
                  key={fig.id}
                  className="overflow-hidden rounded-lg border border-violet-500/25 bg-violet-950/20"
                >
                  {figures.documentId && fig.id && (
                    <img
                      src={figureImageUrl(figures.documentId, fig.id)}
                      alt={fig.caption || fig.image_type || "figure"}
                      className="max-h-36 w-full object-contain bg-slate-950/60"
                      loading="lazy"
                    />
                  )}
                  <div className="space-y-1 px-3 py-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      {fig.image_type && (
                        <span className="rounded bg-violet-500/20 px-1.5 py-0.5 uppercase tracking-wide text-violet-200">
                          {t(`entityPanel.imageType.${fig.image_type}`) || fig.image_type}
                        </span>
                      )}
                      {fig.page_number != null && (
                        <span className="text-slate-500">
                          {t("entityPanel.figurePage", { page: fig.page_number })}
                        </span>
                      )}
                    </div>
                    <p className="text-slate-300">
                      {fig.caption?.trim() || t("entityPanel.figureNoCaption")}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
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
            {exp.code && (
              <div className="font-mono text-xs text-slate-500">{exp.code}</div>
            )}
            {exp.description && (
              <p className="rounded-lg bg-slate-800/50 p-3 text-sm leading-relaxed text-slate-300">
                {exp.description}
              </p>
            )}
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-slate-800/50 p-2">
                <div className="text-slate-500">{t("entityPanel.status")}</div>
                <div className="mt-0.5 capitalize text-slate-200">
                  {exp.status ?? "—"}
                </div>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2">
                <div className="text-slate-500">{t("entityPanel.started")}</div>
                <div className="mt-0.5 text-slate-200">{exp.startedAt ?? "—"}</div>
              </div>
            </div>
            {(exp.measurements?.length ?? 0) > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-slate-500">{t("entityPanel.measurements")}</div>
                <div className="space-y-2">
                  {exp.measurements!.map((m, i) => (
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

        {isProperty && property && (
          <div className="mt-4">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("entityPanel.measurements")}
              </div>
              {property.unit && (
                <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-200/90">
                  {property.unit}
                </span>
              )}
            </div>
            {property.measurements && property.measurements.length > 0 ? (
              <PropertyMeasurementsList
                measurements={property.measurements}
                emptyLabel={t("entityPanel.noMeasurements")}
              />
            ) : (
              <p className="mt-2 text-xs text-slate-500">{t("entityPanel.noMeasurements")}</p>
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

        {!isArticle &&
          !isExperiment &&
          !isMaterial &&
          !isTeam &&
          !isFacility &&
          !isFigures &&
          !isProperty && null}

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
