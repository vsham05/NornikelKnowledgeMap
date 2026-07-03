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
import { MATERIAL_CLASS_OPTIONS, materialClassLabel } from "@/lib/materialClasses";
import { useI18n } from "@/lib/i18n/I18nProvider";

interface QueryFiltersProps {
  value: StructuredFilters;
  onChange: (filters: StructuredFilters) => void;
  disabled?: boolean;
}

const INPUT =
  "w-full rounded-lg border border-slate-700/80 bg-slate-900/80 px-3 py-2.5 text-sm text-slate-100 shadow-inner shadow-black/10 placeholder:text-slate-600 transition focus:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-45";

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
  removeLabel,
}: {
  label: string;
  onRemove: () => void;
  disabled?: boolean;
  removeLabel: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-cyan-500/25 bg-cyan-950/40 py-0.5 pl-2.5 pr-1 text-[11px] font-medium text-cyan-200/90">
      {label}
      <button
        type="button"
        disabled={disabled}
        onClick={onRemove}
        className="rounded-full p-0.5 text-cyan-400/80 transition hover:bg-cyan-500/20 hover:text-cyan-100 disabled:opacity-40"
        aria-label={removeLabel}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

export function QueryFilters({ value, onChange, disabled }: QueryFiltersProps) {
  const { t, locale } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const activeCount = useMemo(() => countActive(value), [value]);

  const GEO_OPTIONS = useMemo(
    () => [
      { id: "", label: t("filters.geoAny"), short: t("filters.geoAnyShort") },
      { id: "domestic", label: t("filters.geoDomestic"), short: t("filters.geoDomesticShort") },
      {
        id: "international",
        label: t("filters.geoInternational"),
        short: t("filters.geoInternationalShort"),
      },
    ],
    [t]
  );

  const PRESETS = useMemo(
    () => [
      { label: t("filters.presetNickelEw"), filters: { material: "nickel", process: "electrowinning" } },
      { label: t("filters.presetNickelConc"), filters: { material: "nickel", materialClass: "concentrate" } },
      { label: t("filters.presetFluids"), filters: { materialClass: "solution" } },
      { label: t("filters.presetDomestic"), filters: { geography: "domestic" } },
      { label: t("filters.presetLast5"), filters: { yearFrom: 2021 } },
      { label: t("filters.presetHeap"), filters: { process: "heap leaching" } },
    ],
    [t]
  );

  const set = (patch: Partial<StructuredFilters>) => onChange({ ...value, ...patch });

  const chips = useMemo(() => {
    const items: Array<{ key: keyof StructuredFilters; label: string }> = [];
    if (value.material) {
      items.push({ key: "material", label: t("filters.chipMaterial", { value: value.material }) });
    }
    if (value.materialClass) {
      items.push({
        key: "materialClass",
        label: t("filters.chipClass", {
          value: materialClassLabel(value.materialClass, locale),
        }),
      });
    }
    if (value.process) {
      items.push({ key: "process", label: t("filters.chipProcess", { value: value.process }) });
    }
    if (value.geography) {
      const geo = GEO_OPTIONS.find((g) => g.id === value.geography);
      items.push({ key: "geography", label: geo?.short ?? value.geography });
    }
    if (value.yearFrom || value.yearTo) {
      items.push({
        key: "yearFrom",
        label: t("filters.chipYears", {
          from: value.yearFrom ?? "…",
          to: value.yearTo ?? "…",
        }),
      });
    }
    if (value.propertyName) items.push({ key: "propertyName", label: value.propertyName });
    if (value.valueMin != null || value.valueMax != null) {
      items.push({
        key: "valueMin",
        label: t("filters.chipRange", {
          min: value.valueMin ?? "…",
          max: value.valueMax ?? "…",
        }),
      });
    }
    return items;
  }, [value, t, locale, GEO_OPTIONS]);

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
            <p className="text-sm font-medium text-slate-200">{t("filters.title")}</p>
            <p className="truncate text-xs text-slate-500">{t("filters.subtitle")}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {activeCount > 0 && (
            <span className="rounded-full bg-cyan-500/15 px-2.5 py-0.5 text-[11px] font-semibold tabular-nums text-cyan-300">
              {t("filters.active", { count: activeCount })}
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
              removeLabel={t("filters.remove", { label: chip.label })}
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
              {t("filters.quickPresets")}
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
                {t("filters.subjectMatter")}
              </h3>
              <FilterField
                label={t("filters.material")}
                hint={t("filters.materialHint")}
                icon={Layers}
              >
                <input
                  type="text"
                  disabled={disabled}
                  value={value.material ?? ""}
                  onChange={(e) => set({ material: e.target.value || undefined })}
                  placeholder={t("filters.materialPlaceholder")}
                  className={INPUT}
                />
              </FilterField>
              <FilterField
                label={t("filters.materialClass")}
                hint={t("filters.materialClassHint")}
                icon={Layers}
              >
                <select
                  disabled={disabled}
                  value={value.materialClass ?? ""}
                  onChange={(e) => set({ materialClass: e.target.value || undefined })}
                  className={INPUT}
                >
                  <option value="">{t("filters.anyClass")}</option>
                  {MATERIAL_CLASS_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {materialClassLabel(opt.id, locale)} ({opt.stage})
                    </option>
                  ))}
                </select>
              </FilterField>
              <FilterField
                label={t("filters.process")}
                hint={t("filters.processHint")}
                icon={Cog}
              >
                <input
                  type="text"
                  disabled={disabled}
                  value={value.process ?? ""}
                  onChange={(e) => set({ process: e.target.value || undefined })}
                  placeholder={t("filters.processPlaceholder")}
                  className={INPUT}
                />
              </FilterField>
            </section>

            {/* Scope */}
            <section className="space-y-4 lg:col-span-1">
              <h3 className="border-b border-slate-800/80 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
                {t("filters.scope")}
              </h3>
              <FilterField label={t("filters.geography")} icon={Globe2}>
                <div
                  className="flex rounded-lg border border-slate-700/80 bg-slate-950/50 p-1"
                  role="group"
                  aria-label={t("filters.geography")}
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
              <FilterField label={t("filters.period")} icon={CalendarRange}>
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
                    placeholder={t("filters.yearFrom")}
                    className={INPUT}
                    aria-label={t("filters.yearFrom")}
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
                    placeholder={t("filters.yearTo")}
                    className={INPUT}
                    aria-label={t("filters.yearTo")}
                  />
                </div>
              </FilterField>
            </section>

            {/* Measurements */}
            <section className="space-y-4 lg:col-span-1">
              <h3 className="border-b border-slate-800/80 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
                {t("filters.measured")}
              </h3>
              <FilterField
                label={t("filters.property")}
                hint={t("filters.propertyHint")}
                icon={Gauge}
              >
                <input
                  type="text"
                  disabled={disabled}
                  value={value.propertyName ?? ""}
                  onChange={(e) => set({ propertyName: e.target.value || undefined })}
                  placeholder={t("filters.propertyPlaceholder")}
                  className={INPUT}
                />
              </FilterField>
              <FilterField label={t("filters.numericRange")} icon={Gauge}>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    step="any"
                    disabled={disabled}
                    value={value.valueMin ?? ""}
                    onChange={(e) =>
                      set({ valueMin: e.target.value ? Number(e.target.value) : undefined })
                    }
                    placeholder={t("filters.min")}
                    className={INPUT}
                    aria-label={t("filters.min")}
                  />
                  <span className="shrink-0 text-slate-600">{t("filters.to")}</span>
                  <input
                    type="number"
                    step="any"
                    disabled={disabled}
                    value={value.valueMax ?? ""}
                    onChange={(e) =>
                      set({ valueMax: e.target.value ? Number(e.target.value) : undefined })
                    }
                    placeholder={t("filters.max")}
                    className={INPUT}
                    aria-label={t("filters.max")}
                  />
                </div>
              </FilterField>
            </section>
          </div>

          {/* Footer: chips + actions */}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 pt-4">
            <div className="flex min-h-[28px] flex-1 flex-wrap gap-1.5">
              {chips.length === 0 ? (
                <span className="text-xs text-slate-600">{t("filters.noConstraints")}</span>
              ) : (
                chips.map((chip) => (
                  <ActiveChip
                    key={chip.label}
                    label={chip.label}
                    disabled={disabled}
                    removeLabel={t("filters.remove", { label: chip.label })}
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
              {t("filters.resetAll")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
