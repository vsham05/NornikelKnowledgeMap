"use client";

import type { PropertyMeasurement } from "@/lib/types";
import { parsePropertyValue, measurementKey } from "@/lib/formatPropertyValue";
import { useMemo } from "react";

function dedupeMeasurements(rows: PropertyMeasurement[]): PropertyMeasurement[] {
  const seen = new Set<string>();
  const out: PropertyMeasurement[] = [];
  for (const row of rows) {
    const key = measurementKey(row.materialName, row.experimentName, row.value);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

export function PropertyMeasurementsList({
  measurements,
  emptyLabel,
}: {
  measurements: PropertyMeasurement[];
  emptyLabel: string;
}) {
  const rows = useMemo(() => dedupeMeasurements(measurements), [measurements]);

  if (rows.length === 0) {
    return <p className="mt-2 text-xs text-slate-500">{emptyLabel}</p>;
  }

  return (
    <ul className="mt-2 max-h-[min(52vh,420px)] space-y-2 overflow-y-auto pr-1">
      {rows.map((m, idx) => {
        const parsed = parsePropertyValue(m.value, m.unit);
        const context = m.experimentName || m.materialName || `Record ${idx + 1}`;
        return (
          <li
            key={`${context}-${m.value}-${idx}`}
            className="rounded-lg border border-amber-500/20 bg-slate-900/60 px-3 py-2.5"
          >
            <div className="mb-1.5 text-xs font-medium text-slate-300">{context}</div>
            {parsed.kind === "composition" && parsed.elements ? (
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                {parsed.elements.map((el) => (
                  <div
                    key={el.symbol}
                    className="rounded-md border border-slate-700/60 bg-slate-800/50 px-2 py-1.5"
                  >
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">
                      {el.symbol}
                    </div>
                    <div className="text-sm font-semibold text-amber-100">
                      {el.value}
                      {el.unit ? (
                        <span className="ml-0.5 text-[10px] font-normal text-slate-400">
                          {el.unit}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-lg font-semibold text-amber-100">
                {parsed.display}
                {parsed.unit ? (
                  <span className="ml-1 text-sm font-normal text-amber-200/80">
                    {parsed.unit}
                  </span>
                ) : null}
              </div>
            )}
            {m.documentTitle && (
              <div className="mt-1.5 text-[10px] text-slate-500">{m.documentTitle}</div>
            )}
            {m.sourceText && (
              <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-500">
                {m.sourceText}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
