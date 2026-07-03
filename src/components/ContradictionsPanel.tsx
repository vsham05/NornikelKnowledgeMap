"use client";

import { useEffect, useState } from "react";
import { Scale } from "lucide-react";
import { backendApi } from "@/lib/api/backend";
import { useI18n } from "@/lib/i18n/I18nProvider";

interface Contradiction {
  material: string;
  property: string;
  value_a: string;
  value_b: string;
  source_a?: string;
  source_b?: string;
  description: string;
}

interface ContradictionsPanelProps {
  enabled?: boolean;
}

export function ContradictionsPanel({ enabled }: ContradictionsPanelProps) {
  const { t } = useI18n();
  const [items, setItems] = useState<Contradiction[]>([]);

  useEffect(() => {
    if (!enabled) return;
    backendApi
      .contradictions()
      .then((r) => setItems(r.contradictions ?? []))
      .catch(() => setItems([]));
  }, [enabled]);

  if (!enabled) return null;

  if (!items.length) {
    return (
      <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4 text-xs text-slate-500">
        <Scale className="mb-1 inline h-3.5 w-3.5 text-slate-400" /> {t("contradictions.empty")}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-950/10 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-amber-200">
        <Scale className="h-4 w-4" />
        {t("contradictions.title", { count: items.length })}
      </div>
      <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto text-xs">
        {items.map((c, i) => (
          <li key={i} className="rounded-lg border border-amber-500/20 bg-slate-950/40 p-2">
            <p className="font-medium text-amber-100">{c.material} · {c.property}</p>
            <p className="mt-1 text-slate-300">
              <span className="text-red-300">{c.value_a}</span>
              {t("contradictions.vs")}
              <span className="text-cyan-300">{c.value_b}</span>
            </p>
            {(c.source_a || c.source_b) && (
              <p className="mt-1 text-slate-500">
                {c.source_a && `A: ${c.source_a}`}
                {c.source_a && c.source_b && " · "}
                {c.source_b && `B: ${c.source_b}`}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
