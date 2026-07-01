"use client";

import { useEffect, useState, useRef } from "react";
import { BookOpen, FlaskConical, Layers, Users, GitBranch } from "lucide-react";
import { backendApi } from "@/lib/api/backend";
import type { EntityType } from "@/lib/types";

interface StatsBarProps {
  useBackend?: boolean;
  refreshKey?: number;
  activeFilter?: EntityType | null;
  onFilterChange?: (filter: EntityType | null) => void;
}

const EMPTY_STATS = {
  articles: 0,
  experiments: 0,
  materials: 0,
  modes: 0,
  teams: 0,
  completed: 0,
  ongoing: 0,
  planned: 0,
};

export function StatsBar({
  useBackend,
  refreshKey = 0,
  activeFilter,
  onFilterChange,
}: StatsBarProps) {
  const [backendStats, setBackendStats] = useState<typeof EMPTY_STATS | null>(null);
  const enrichAttempted = useRef(false);

  useEffect(() => {
    if (!useBackend) {
      setBackendStats(null);
      return;
    }
    backendApi
      .graphStats()
      .then((s) => {
        const status = s.experiment_status ?? {};
        const emptyGraph =
          (s.documents ?? 0) > 0 &&
          (s.materials ?? 0) === 0 &&
          (s.experiments ?? 0) === 0;
        if (emptyGraph && !enrichAttempted.current) {
          enrichAttempted.current = true;
          void backendApi.enrichAllDocuments().then(() =>
            backendApi.graphStats().then((fresh) => {
              const st = fresh.experiment_status ?? {};
              setBackendStats({
                articles: fresh.documents ?? 0,
                experiments: fresh.experiments ?? 0,
                materials: fresh.materials ?? 0,
                modes: fresh.regimeparameters ?? Object.keys(fresh.regime_types ?? {}).length,
                teams: fresh.teams ?? 0,
                completed: st.completed ?? fresh.experiments ?? 0,
                ongoing: st.ongoing ?? 0,
                planned: st.planned ?? 0,
              });
            })
          );
          return;
        }
        setBackendStats({
          articles: s.documents ?? 0,
          experiments: s.experiments ?? 0,
          materials: s.materials ?? 0,
          modes: s.regimeparameters ?? Object.keys(s.regime_types ?? {}).length,
          teams: s.teams ?? 0,
          completed: status.completed ?? s.experiments ?? 0,
          ongoing: status.ongoing ?? 0,
          planned: status.planned ?? 0,
        });
      })
      .catch(() => setBackendStats(null));
  }, [useBackend, refreshKey]);

  const stats = backendStats ?? EMPTY_STATS;

  const items: Array<{
    icon: typeof BookOpen;
    label: string;
    value: number;
    color: string;
    filter: EntityType | null;
  }> = [
    { icon: BookOpen, label: "Documents", value: stats.articles, color: "text-blue-400", filter: "article" },
    { icon: FlaskConical, label: "Experiments", value: stats.experiments, color: "text-emerald-400", filter: "experiment" },
    { icon: Layers, label: "Materials", value: stats.materials, color: "text-pink-400", filter: "material" },
    { icon: GitBranch, label: "Modes", value: stats.modes, color: "text-violet-400", filter: "mode" },
    { icon: Users, label: "Teams", value: stats.teams, color: "text-orange-400", filter: "team" },
  ];

  return (
    <div className="flex flex-wrap gap-4">
      {items.map(({ icon: Icon, label, value, color, filter }) => {
        const selected = activeFilter === filter;
        return (
        <button
          key={label}
          type="button"
          disabled={!onFilterChange || value === 0}
          onClick={() =>
            onFilterChange?.(selected ? null : filter)
          }
          title={onFilterChange ? `Highlight ${label} in graph` : undefined}
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition-colors ${
            selected
              ? "border-cyan-500/50 bg-cyan-950/30"
              : "border-slate-700/40 bg-slate-900/40 hover:border-slate-600"
          } disabled:cursor-default disabled:opacity-60`}
        >
          <Icon className={`h-4 w-4 ${color}`} />
          <span className="text-lg font-semibold text-slate-100">{value}</span>
          <span className="text-xs text-slate-500">{label}</span>
        </button>
        );
      })}
      {useBackend && backendStats && (
        <span className="self-center text-xs text-cyan-500">Live · Neo4j</span>
      )}
      {!useBackend && (
        <span className="self-center text-xs text-amber-500">Backend offline</span>
      )}
      <div className="ml-auto flex items-center gap-3 text-xs text-slate-500">
        <span>
          <span className="text-emerald-400">{stats.completed}</span> completed
        </span>
        <span>
          <span className="text-amber-400">{stats.ongoing}</span> ongoing
        </span>
        <span>
          <span className="text-slate-400">{stats.planned}</span> planned
        </span>
      </div>
    </div>
  );
}
