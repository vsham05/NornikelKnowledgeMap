"use client";

import { useMemo, useState } from "react";
import {
  SlidersHorizontal,
  ChevronDown,
  X,
  Layers,
  Cog,
  Globe2,
  CalendarRange,
  Gauge,
  RotateCcw,
} from "lucide-react";
import clsx from "clsx";
import type { StructuredFilters } from "@/lib/types";

interface QueryFiltersProps {
  value: StructuredFilters;
  onChange: (filters: StructuredFilters) => void;
  disabled?: boolean;
}

const INPUT =
  "w-full rounded-lg border border-slate-700/80 bg-slate-900/80 px-3 py-2.5 text-sm text-slate-100 shadow-inner shadow-black/10 placeholder:text-slate-600 transition focus:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-45";

const GEO_OPTIONS: Array<{ id: string; label: string; short: string }> = [
  { id: "", label: "Any region", short: "Any" },
  { id: "domestic", label: "Russia / CIS practice", short: "Domestic" },
  { id: "international", label: "International & global literature", short: "Global" },
];

const PRESETS: Array<{ label: string; filters: StructuredFilters }> = [
  { label: "Nickel electrowinning", filters: { material: "nickel", process: "electrowinning" } },
  { label: "Domestic practice", filters: { geography: "domestic" } },
  { label: "Last 5 years", filters: { yearFrom: 2021 } },
  { label: "Heap leaching", filters: { process: "heap leaching" } },
];

function countActive(filters: StructuredFilters): number {
  return Object.values(filters).filter((v) => v !== undefined && v !== "").length;
}

function FilterField({
  label,
  hint,
  icon: Icon,
  children,
}: {
  label: string;
  hint?: string;
  icon: typeof Layers;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-slate-500" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          {label}
        </span>
      </div>
      {children}
      {hint && <p className="text-[11px] leading-snug text-slate-600">{hint}</p>}
    </div>
  );
}

function ActiveChip({
  label,
  onRemove,
  disabled,
}: {
  label: string;
  onRemove: () => void;
  disabled?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-cyan-500/25 bg-cyan-950/40 py-0.5 pl-2.5 pr-1 text-[11px] font-medium text-cyan-200/90">
      {label}
      <button
        type="button"
        disabled={disabled}
        onClick={onRemove}
        className="rounded-full p-0.5 text-cyan-400/80 transition hover:bg-cyan-500/20 hover:text-cyan-100 disabled:opacity-40"
        aria-label={`Remove ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

export function QueryFilters({ value, onChange, disabled }: QueryFiltersProps) {
  const [expanded, setExpanded] = useState(false);
  const activeCount = useMemo(() => countActive(value), [value]);

  const set = (patch: Partial<StructuredFilters>) => onChange({ ...value, ...patch });

  const chips = useMemo(() => {
    const items: Array<{ key: keyof StructuredFilters; label: string }> = [];
    if (value.material) items.push({ key: "material", label: `Material: ${value.material}` });
    if (value.process) items.push({ key: "process", label: `Process: ${value.process}` });
    if (value.geography) {
      const geo = GEO_OPTIONS.find((g) => g.id === value.geography);
      items.push({ key: "geography", label: geo?.short ?? value.geography });
    }
    if (value.yearFrom || value.yearTo) {
      items.push({
        key: "yearFrom",
        label: `Years: ${value.yearFrom ?? "…"}–${value.yearTo ?? "…"}`,
      });
    }
    if (value.propertyName) items.push({ key: "propertyName", label: value.propertyName });
    if (value.valueMin != null || value.valueMax != null) {
      items.push({
        key: "valueMin",
        label: `Range: ${value.valueMin ?? "…"} – ${value.valueMax ?? "…"}`,
      });
    }
    return items;
  }, [value]);

  const removeChip = (key: keyof StructuredFilters) => {
    if (key === "yearFrom") {
      onChange({ ...value, yearFrom: undefined, yearTo: undefined });
      return;
    }
    if (key === "valueMin") {
      onChange({ ...value, valueMin: undefined, valueMax: undefined });
      return;
    }
    onChange({ ...value, [key]: undefined });
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-700/60 bg-gradient-to-b from-slate-900/70 to-slate-950/80 shadow-lg shadow-black/15">
      {/* Header */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-slate-800/30 disabled:cursor-not-allowed disabled:opacity-50"
        aria-expanded={expanded}
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-600/40 bg-slate-800/60">
            <SlidersHorizontal className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-slate-200">Query constraints</p>
            <p className="truncate text-xs text-slate-500">
              Refine by material, process, geography, period & measured parameters
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {activeCount > 0 && (
            <span className="rounded-full bg-cyan-500/15 px-2.5 py-0.5 text-[11px] font-semibold tabular-nums text-cyan-300">
              {activeCount} active
            </span>
          )}
          <ChevronDown
            className={clsx(
              "h-4 w-4 text-slate-500 transition-transform duration-200",
              expanded && "rotate-180"
            )}
          />
        </div>
      </button>

      {/* Collapsed: active chips only */}
      {!expanded && chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-t border-slate-800/80 px-4 py-2.5">
          {chips.map((chip) => (
            <ActiveChip
              key={chip.label}
              label={chip.label}
              disabled={disabled}
              onRemove={() => removeChip(chip.key)}
            />
          ))}
        </div>
      )}

      {/* Expanded panel */}
      {expanded && (
        <div className="border-t border-slate-800/80 px-4 pb-4 pt-3">
          {/* Quick presets */}
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">
              Quick presets
            </span>
            {PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                disabled={disabled}
                onClick={() => onChange({ ...value, ...preset.filters })}
                className="rounded-full border border-slate-700/80 bg-slate-900/60 px-2.5 py-1 text-[11px] text-slate-400 transition hover:border-slate-600 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40"
              >
                {preset.label}
              </button>
            ))}
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Subject matter */}
            <section className="space-y-4 lg:col-span-1">
              <h3 className="border-b border-slate-800/80 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
                Subject matter
              </h3>
              <FilterField
                label="Material"
                hint="Substance, ore, product, or electrolyte"
                icon={Layers}
              >
                <input
                  type="text"
                  disabled={disabled}
                  value={value.material ?? ""}
                  onChange={(e) => set({ material: e.target.value || undefined })}
                  placeholder="e.g. nickel cathode, copper matte"
                  className={INPUT}
                />
              </FilterField>
              <FilterField
                label="Process"
                hint="Technology or unit operation"
                icon={Cog}
              >
                <input
                  type="text"
                  disabled={disabled}
                  value={value.process ?? ""}
                  onChange={(e) => set({ process: e.target.value || undefined })}
                  placeholder="e.g. electrowinning, heap leaching"
                  className={INPUT}
                />
              </FilterField>
            </section>

            {/* Scope */}
            <section className="space-y-4 lg:col-span-1">
              <h3 className="border-b border-slate-800/80 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
                Scope & provenance
              </h3>
              <FilterField label="Geography" icon={Globe2}>
                <div
                  className="flex rounded-lg border border-slate-700/80 bg-slate-950/50 p-1"
                  role="group"
                  aria-label="Geography filter"
                >
                  {GEO_OPTIONS.map((opt) => (
                    <button
                      key={opt.id || "any"}
                      type="button"
                      disabled={disabled}
                      title={opt.label}
                      onClick={() => set({ geography: opt.id || undefined })}
                      className={clsx(
                        "flex-1 rounded-md px-2 py-2 text-xs font-medium transition",
                        (value.geography ?? "") === opt.id
                          ? "bg-cyan-600/90 text-white shadow-sm"
                          : "text-slate-400 hover:bg-slate-800/80 hover:text-slate-200"
                      )}
                    >
                      {opt.short}
                    </button>
                  ))}
                </div>
              </FilterField>
              <FilterField label="Publication period" icon={CalendarRange}>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={1900}
                    max={2100}
                    disabled={disabled}
                    value={value.yearFrom ?? ""}
                    onChange={(e) =>
                      set({ yearFrom: e.target.value ? Number(e.target.value) : undefined })
                    }
                    placeholder="From"
                    className={INPUT}
                    aria-label="Year from"
                  />
                  <span className="shrink-0 text-slate-600">—</span>
                  <input
                    type="number"
                    min={1900}
                    max={2100}
                    disabled={disabled}
                    value={value.yearTo ?? ""}
                    onChange={(e) =>
                      set({ yearTo: e.target.value ? Number(e.target.value) : undefined })
                    }
                    placeholder="To"
                    className={INPUT}
                    aria-label="Year to"
                  />
                </div>
              </FilterField>
            </section>

            {/* Measurements */}
            <section className="space-y-4 lg:col-span-1">
              <h3 className="border-b border-slate-800/80 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
                Measured parameters
              </h3>
              <FilterField
                label="Property"
                hint="Concentration, flow rate, temperature, recovery…"
                icon={Gauge}
              >
                <input
                  type="text"
                  disabled={disabled}
                  value={value.propertyName ?? ""}
                  onChange={(e) => set({ propertyName: e.target.value || undefined })}
                  placeholder="e.g. catholyte flow rate"
                  className={INPUT}
                />
              </FilterField>
              <FilterField label="Numeric range" icon={Gauge}>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    step="any"
                    disabled={disabled}
                    value={value.valueMin ?? ""}
                    onChange={(e) =>
                      set({ valueMin: e.target.value ? Number(e.target.value) : undefined })
                    }
                    placeholder="Min"
                    className={INPUT}
                    aria-label="Minimum value"
                  />
                  <span className="shrink-0 text-slate-600">to</span>
                  <input
                    type="number"
                    step="any"
                    disabled={disabled}
                    value={value.valueMax ?? ""}
                    onChange={(e) =>
                      set({ valueMax: e.target.value ? Number(e.target.value) : undefined })
                    }
                    placeholder="Max"
                    className={INPUT}
                    aria-label="Maximum value"
                  />
                </div>
              </FilterField>
            </section>
          </div>

          {/* Footer: chips + actions */}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 pt-4">
            <div className="flex min-h-[28px] flex-1 flex-wrap gap-1.5">
              {chips.length === 0 ? (
                <span className="text-xs text-slate-600">No constraints applied — search uses full corpus</span>
              ) : (
                chips.map((chip) => (
                  <ActiveChip
                    key={chip.label}
                    label={chip.label}
                    disabled={disabled}
                    onRemove={() => removeChip(chip.key)}
                  />
                ))
              )}
            </div>
            <button
              type="button"
              disabled={disabled || activeCount === 0}
              onClick={() => onChange({})}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-600/80 bg-slate-900/60 px-3 py-2 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:bg-slate-800 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset all
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
