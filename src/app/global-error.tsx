"use client";

import { translate } from "@/lib/i18n/translations";

function detectLocale(): "en" | "ru" {
  if (typeof window === "undefined") return "en";
  const stored = window.localStorage.getItem("rd-knowledge-locale");
  if (stored === "en" || stored === "ru") return stored;
  return navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en";
}

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const locale = detectLocale();
  const t = (key: string) => translate(locale, key);

  return (
    <html lang={locale}>
      <body className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 p-8 text-slate-100">
        <h2 className="text-xl font-semibold">{t("error.title")}</h2>
        <p className="max-w-md text-center text-sm text-slate-400">
          {error.message || t("error.unexpected")}
        </p>
        <button
          type="button"
          onClick={() => reset()}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm text-white hover:bg-cyan-500"
        >
          {t("error.tryAgain")}
        </button>
      </body>
    </html>
  );
}
