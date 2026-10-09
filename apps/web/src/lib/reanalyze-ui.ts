/** Pure helpers for the documents-list re-analyze control (fixture-friendly). */

export function canSubmitReanalyze(selectedCount: number, analyzing: boolean): boolean {
  return selectedCount > 0 && !analyzing;
}

export function reanalyzeButtonLabel(
  selectedCount: number,
  analyzing: boolean,
  labels: { idle: string; withCount: (n: number) => string; analyzing: string },
): string {
  if (analyzing) return labels.analyzing;
  if (selectedCount <= 0) return labels.idle;
  return labels.withCount(selectedCount);
}

export function toggleIdInSet(selected: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export function applyReanalyzeResults<T extends { id: string; school_action?: string | null }>(
  items: T[],
  results: Array<{ document_id: string; ok: boolean; school_action?: string | null }>,
): T[] {
  const byId = new Map(results.map((r) => [r.document_id, r]));
  return items.map((item) => {
    const hit = byId.get(item.id);
    if (!hit) return item;
    if (hit.ok && hit.school_action) {
      return { ...item, school_action: hit.school_action };
    }
    // Failure: keep previous school_action (do not blank it).
    return item;
  });
}
