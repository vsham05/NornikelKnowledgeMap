import type { DataGap } from "@/lib/types";
import { AlertTriangle } from "lucide-react";
import clsx from "clsx";

const PRIORITY_STYLE = {
  high: "border-red-500/30 bg-red-950/20 text-red-300",
  medium: "border-amber-500/30 bg-amber-950/20 text-amber-300",
  low: "border-slate-600/30 bg-slate-800/30 text-slate-400",
};

interface GapAnalysisProps {
  gaps: DataGap[];
}

export function GapAnalysis({ gaps }: GapAnalysisProps) {
  if (gaps.length === 0) {
    return (
      <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-4 text-sm text-emerald-300">
        No significant data gaps detected for this query scope.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
        <AlertTriangle className="h-4 w-4 text-amber-400" />
        Data Gaps ({gaps.length})
      </div>
      <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
        {gaps.map((gap, i) => (
          <div
            key={`${gap.material}-${gap.mode}-${gap.property}-${i}`}
            className={clsx(
              "rounded-lg border p-3 text-xs",
              PRIORITY_STYLE[gap.priority]
            )}
          >
            <div className="font-medium">
              {gap.material} · {gap.mode} · {gap.property}
            </div>
            <p className="mt-1 opacity-80">{gap.reason}</p>
            <span className="mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] uppercase opacity-70">
              {gap.priority} priority
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
