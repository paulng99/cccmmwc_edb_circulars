/**
 * Calendar / homepage / document-activity main title lines (same type size).
 * Line 1: activity or deadline item; line 2: notice title.
 * Missing item name → notice title only. Same text → once.
 */
export function agendaTitleLines(
  activityName: string | null | undefined,
  documentTitle: string | null | undefined,
): string[] {
  const item = activityName?.trim() || "";
  const doc = documentTitle?.trim() || "";
  if (!item) return doc ? [doc] : [];
  if (!doc || item === doc) return [item];
  return [item, doc];
}

/** Optional summary / location lines; empty values are omitted (no blank rows). */
export function agendaDetailLines(
  summary: string | null | undefined,
  location: string | null | undefined,
): string[] {
  const lines: string[] = [];
  const s = summary?.trim() || "";
  const loc = location?.trim() || "";
  if (s) lines.push(s);
  if (loc) lines.push(loc);
  return lines;
}
