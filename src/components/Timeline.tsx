import type { ExperimentResult } from "@/lib/types";
import { Calendar } from "lucide-react";

interface TimelineProps {
  experiments: ExperimentResult[];
}

export function Timeline({ experiments }: TimelineProps) {
  const sorted = [...experiments].sort(
    (a, b) =>
      new Date(a.experiment.startedAt).getTime() -
      new Date(b.experiment.startedAt).getTime()
  );

  if (sorted.length === 0) return null;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
        <Calendar className="h-4 w-4 text-cyan-400" />
        Research History
      </div>
      <div className="relative ml-3 border-l border-slate-700 pl-5">
        {sorted.map((r, i) => (
          <div key={r.experiment.id} className="relative pb-4 last:pb-0">
            <span
              className="absolute -left-[1.35rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-slate-900"
              style={{
                backgroundColor:
                  r.experiment.status === "completed"
                    ? "#34d399"
                    : r.experiment.status === "ongoing"
                      ? "#fbbf24"
                      : "#64748b",
              }}
            />
            <div className="text-xs text-slate-500">
              {r.experiment.startedAt}
              {r.experiment.completedAt && ` → ${r.experiment.completedAt}`}
            </div>
            <div className="text-sm font-medium text-slate-200">{r.experiment.name}</div>
            <div className="text-xs text-slate-400">
              {r.material.name} / {r.mode.name}
            </div>
            {i < sorted.length - 1 && (
              <div className="mt-1 text-[10px] text-slate-600">
                {daysBetween(r.experiment.completedAt ?? r.experiment.startedAt, sorted[i + 1].experiment.startedAt)} days later
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function daysBetween(a: string, b: string): number {
  const ms = Math.abs(new Date(b).getTime() - new Date(a).getTime());
  return Math.round(ms / (1000 * 60 * 60 * 24));
}
