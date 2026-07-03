"use client";

import { Globe } from "lucide-react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Locale } from "@/lib/i18n/translations";

const OPTIONS: Locale[] = ["en", "ru"];

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="flex items-center gap-2">
      <Globe className="h-3.5 w-3.5 text-slate-500" aria-hidden />
      <label htmlFor="locale-select" className="sr-only">
        {t("lang.label")}
      </label>
      <select
        id="locale-select"
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        className="rounded-lg border border-slate-700/80 bg-slate-900/80 px-2.5 py-1.5 text-xs text-slate-200 focus:border-cyan-500/60 focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
        aria-label={t("lang.label")}
      >
        {OPTIONS.map((code) => (
          <option key={code} value={code}>
            {t(`lang.${code}`)}
          </option>
        ))}
      </select>
    </div>
  );
}
