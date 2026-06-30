"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 p-8 text-slate-100">
        <h2 className="text-xl font-semibold">Something went wrong</h2>
        <p className="max-w-md text-center text-sm text-slate-400">
          {error.message || "An unexpected error occurred."}
        </p>
        <button
          type="button"
          onClick={() => reset()}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm text-white hover:bg-cyan-500"
        >
          Try again
        </button>
      </body>
    </html>
  );
}
