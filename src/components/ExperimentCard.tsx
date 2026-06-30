import type { ExperimentResult } from "@/lib/types";
import { FlaskConical, Users, ArrowRight, CheckCircle2, Clock, CircleDashed } from "lucide-react";
import clsx from "clsx";

const STATUS_ICON = {
  completed: CheckCircle2,
  ongoing: Clock,
  planned: CircleDashed,
};

const STATUS_COLOR = {
  completed: "text-emerald-400",
  ongoing: "text-amber-400",
  planned: "text-slate-500",
};

const EFFECT_BADGE = {
  positive: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  negative: "bg-red-500/20 text-red-300 border-red-500/30",
  neutral: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  mixed: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

interface ExperimentCardProps {
  result: ExperimentResult;
  selected?: boolean;
  onClick?: () => void;
}

export function ExperimentCard({ result, selected, onClick }: ExperimentCardProps) {
  const { experiment, material, mode, team, conclusion, relevance, effectSummary } = result;
  const StatusIcon = STATUS_ICON[experiment.status];

  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "w-full rounded-xl border p-4 text-left transition",
        selected
          ? "border-cyan-500/50 bg-cyan-950/30 shadow-lg shadow-cyan-500/5"
          : "border-slate-700/60 bg-slate-900/50 hover:border-slate-600 hover:bg-slate-800/50"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 shrink-0 text-emerald-400" />
            <span className="truncate font-medium text-slate-100">{experiment.name}</span>
          </div>
          <p className="mt-1 font-mono text-xs text-slate-500">{experiment.code}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-cyan-400">
            {relevance}% match
          </span>
          <StatusIcon className={clsx("h-4 w-4", STATUS_COLOR[experiment.status])} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span className="rounded-md bg-pink-500/10 px-2 py-0.5 text-pink-300">{material.name}</span>
        <ArrowRight className="h-3 w-3" />
        <span className="rounded-md bg-violet-500/10 px-2 py-0.5 text-violet-300">{mode.name}</span>
      </div>

      <p className="mt-3 text-sm text-slate-300">{effectSummary}</p>

      {conclusion && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-slate-800/50 p-2">
          <span
            className={clsx(
              "shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase",
              EFFECT_BADGE[conclusion.effect]
            )}
          >
            {conclusion.effect}
          </span>
          <p className="text-xs text-slate-400 line-clamp-2">{conclusion.summary}</p>
        </div>
      )}

      <div className="mt-3 flex items-center gap-1 text-xs text-slate-500">
        <Users className="h-3 w-3" />
        {team.name}
        <span className="mx-1">·</span>
        {experiment.completedAt ?? experiment.startedAt}
      </div>
    </button>
  );
}
