"use client";

import { useEffect, useState } from "react";
import { BookOpen, FlaskConical, Layers, Users, GitBranch } from "lucide-react";
import { backendApi } from "@/lib/api/backend";

interface StatsBarProps {
  useBackend?: boolean;
  refreshKey?: number;
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

export function StatsBar({ useBackend, refreshKey = 0 }: StatsBarProps) {
  const [backendStats, setBackendStats] = useState<typeof EMPTY_STATS | null>(null);

  useEffect(() => {
    if (!useBackend) {
      setBackendStats(null);
      return;
    }
    backendApi
      .graphStats()
      .then((s) => {
        setBackendStats({
          articles: s.documents ?? 0,
          experiments: s.experiments ?? 0,
          materials: s.materials ?? 0,
          modes: Object.keys(s.regime_types ?? {}).length || 0,
          teams: 0,
          completed: s.experiments ?? 0,
          ongoing: 0,
          planned: 0,
        });
      })
      .catch(() => setBackendStats(null));
  }, [useBackend, refreshKey]);

  const stats = backendStats ?? EMPTY_STATS;

  const items = [
    { icon: BookOpen, label: "Documents", value: stats.articles, color: "text-blue-400" },
    { icon: FlaskConical, label: "Experiments", value: stats.experiments, color: "text-emerald-400" },
    { icon: Layers, label: "Materials", value: stats.materials, color: "text-pink-400" },
    { icon: GitBranch, label: "Modes", value: stats.modes, color: "text-violet-400" },
    { icon: Users, label: "Teams", value: stats.teams, color: "text-orange-400" },
  ];

  return (
    <div className="flex flex-wrap gap-4">
      {items.map(({ icon: Icon, label, value, color }) => (
        <div
          key={label}
          className="flex items-center gap-2 rounded-lg border border-slate-700/40 bg-slate-900/40 px-3 py-2"
        >
          <Icon className={`h-4 w-4 ${color}`} />
          <span className="text-lg font-semibold text-slate-100">{value}</span>
          <span className="text-xs text-slate-500">{label}</span>
        </div>
      ))}
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
