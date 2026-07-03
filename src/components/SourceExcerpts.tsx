"use client";

import { useState } from "react";
import { BookOpen, ChevronDown, ChevronUp } from "lucide-react";
import type { SourceExcerpt } from "@/lib/types";
import { useI18n } from "@/lib/i18n/I18nProvider";

interface SourceExcerptsProps {
  sources: SourceExcerpt[];
}

function truncate(text: string, max = 320) {
  if (text.length <= max) return text;
  return `${text.slice(0, max).trim()}…`;
}

export function SourceExcerpts({ sources }: SourceExcerptsProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [showAll, setShowAll] = useState(false);

  if (!sources.length) return null;

  const visible = showAll ? sources : sources.slice(0, 3);

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-4">
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-cyan-400" />
        <p className="text-sm font-medium text-slate-300">{t("sources.title")}</p>
        <span className="text-xs text-slate-500">{t("sources.hint")}</span>
      </div>

      <ul className="mt-3 space-y-2">
        {visible.map((source) => {
          const isOpen = expanded[source.index];
          const preview = truncate(source.text);
          const needsExpand = source.text.length > preview.length;

          return (
            <li
              key={source.index}
              className="rounded-lg border border-slate-800 bg-slate-950/50 p-3"
            >
              <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 rounded bg-cyan-600/20 px-1.5 py-0.5 text-xs font-semibold text-cyan-300">
                  [{source.index}]
                </span>
                <div className="min-w-0 flex-1">
                  {source.title && (
                    <p className="text-xs font-medium text-slate-400">{source.title}</p>
                  )}
                  <p className="mt-1 text-xs leading-relaxed text-slate-300">
                    {isOpen ? source.text : preview}
                  </p>
                  {needsExpand && (
                    <button
                      type="button"
                      onClick={() =>
                        setExpanded((prev) => ({ ...prev, [source.index]: !prev[source.index] }))
                      }
                      className="mt-1.5 flex items-center gap-0.5 text-xs text-cyan-400 hover:text-cyan-300"
                    >
                      {isOpen ? (
                        <>
                          <ChevronUp className="h-3 w-3" /> {t("sources.showLess")}
                        </>
                      ) : (
                        <>
                          <ChevronDown className="h-3 w-3" /> {t("sources.showFull")}
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {sources.length > 3 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-xs text-slate-400 hover:text-slate-300"
        >
          {showAll
            ? t("sources.showFewer")
            : t("sources.showAll", { count: sources.length })}
        </button>
      )}
    </div>
  );
}
