/** Map improve-system-prompt API errors (`throw new Error(await res.text())`) to UI copy. */
export function improveSystemPromptErrorMessage(err: unknown, fallback: string): string {
  const raw = (err instanceof Error ? err.message : String(err ?? "")).trim();
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const detail = parsed?.detail;
    if (detail === "prompt_empty" || detail === "improve_failed") {
      return fallback;
    }
    if (typeof detail === "string" && detail.trim()) return detail;
  } catch {
    /* use fallback below */
  }
  return fallback;
}
