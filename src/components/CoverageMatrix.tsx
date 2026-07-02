"use client";

import { useEffect, useState } from "react";
import { Grid3x3 } from "lucide-react";
import { backendApi } from "@/lib/api/backend";

interface CoverageMatrixProps {
  enabled?: boolean;
}

export function CoverageMatrix({ enabled }: CoverageMatrixProps) {
  const [data, setData] = useState<{
    materials: Array<{ material: string; properties: string[] }>;
    properties: string[];
  } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    backendApi
      .coverageMatrix()
      .then(setData)
      .catch(() => setData(null));
  }, [enabled]);

  if (!enabled || !data?.materials.length) return null;

  const props = data.properties.slice(0, 8);

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
        <Grid3x3 className="h-4 w-4 text-violet-400" />
        Coverage matrix (material × property)
      </div>
      <p className="mt-1 text-xs text-slate-500">Empty cells = knowledge gaps</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[280px] border-collapse text-[10px]">
          <thead>
            <tr>
              <th className="border border-slate-700/50 p-1 text-left text-slate-500">Material</th>
              {props.map((p) => (
                <th
                  key={p}
                  className="max-w-[72px] truncate border border-slate-700/50 p-1 text-slate-500"
                  title={p}
                >
                  {p.length > 10 ? `${p.slice(0, 9)}…` : p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.materials.slice(0, 12).map((row) => (
              <tr key={row.material}>
                <td className="border border-slate-700/50 p-1 text-slate-300">{row.material}</td>
                {props.map((p) => {
                  const has = row.properties?.includes(p);
                  return (
                    <td
                      key={p}
                      className={`border border-slate-700/50 p-1 text-center ${
                        has ? "bg-emerald-900/40 text-emerald-300" : "bg-slate-950/60 text-slate-600"
                      }`}
                    >
                      {has ? "✓" : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
