"use client";

import type { StructuredFilters } from "@/lib/types";

interface QueryFiltersProps {
  value: StructuredFilters;
  onChange: (filters: StructuredFilters) => void;
  disabled?: boolean;
}

export function QueryFilters({ value, onChange, disabled }: QueryFiltersProps) {
  const set = (patch: Partial<StructuredFilters>) => onChange({ ...value, ...patch });

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/30 p-3">
      <p className="mb-2 text-xs font-medium text-slate-400">
        Structured filters — material · process · geography · year · numeric limits
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <input
          type="text"
          placeholder="Material (Ni, catholyte…)"
          disabled={disabled}
          value={value.material ?? ""}
          onChange={(e) => set({ material: e.target.value || undefined })}
          className="rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
        />
        <input
          type="text"
          placeholder="Process (electrowinning…)"
          disabled={disabled}
          value={value.process ?? ""}
          onChange={(e) => set({ process: e.target.value || undefined })}
          className="rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
        />
        <select
          disabled={disabled}
          value={value.geography ?? ""}
          onChange={(e) => set({ geography: e.target.value || undefined })}
          className="rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
        >
          <option value="">Geography — any</option>
          <option value="domestic">Domestic (Russia/CIS)</option>
          <option value="international">International / global</option>
        </select>
        <div className="flex gap-1">
          <input
            type="number"
            placeholder="Year from"
            disabled={disabled}
            value={value.yearFrom ?? ""}
            onChange={(e) =>
              set({ yearFrom: e.target.value ? Number(e.target.value) : undefined })
            }
            className="w-full rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
          />
          <input
            type="number"
            placeholder="Year to"
            disabled={disabled}
            value={value.yearTo ?? ""}
            onChange={(e) =>
              set({ yearTo: e.target.value ? Number(e.target.value) : undefined })
            }
            className="w-full rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
          />
        </div>
        <input
          type="text"
          placeholder="Property (flow rate, concentration…)"
          disabled={disabled}
          value={value.propertyName ?? ""}
          onChange={(e) => set({ propertyName: e.target.value || undefined })}
          className="rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
        />
        <input
          type="number"
          placeholder="Value min"
          disabled={disabled}
          value={value.valueMin ?? ""}
          onChange={(e) =>
            set({ valueMin: e.target.value ? Number(e.target.value) : undefined })
          }
          className="rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
        />
        <input
          type="number"
          placeholder="Value max"
          disabled={disabled}
          value={value.valueMax ?? ""}
          onChange={(e) =>
            set({ valueMax: e.target.value ? Number(e.target.value) : undefined })
          }
          className="rounded-lg border border-slate-700 bg-slate-950/50 px-2 py-1.5 text-xs text-slate-200"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange({})}
          className="rounded-lg border border-slate-600 px-2 py-1.5 text-xs text-slate-400 hover:bg-slate-800"
        >
          Clear filters
        </button>
      </div>
    </div>
  );
}
