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

/** Expand selected group primary ids to every language variant id. */
export function expandSelectedDocumentIds<T extends { primary_id: string; variants: Array<{ id: string }> }>(
  groups: T[],
  selectedPrimaryIds: ReadonlySet<string>,
): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    if (!selectedPrimaryIds.has(group.primary_id)) continue;
    for (const variant of group.variants) {
      if (seen.has(variant.id)) continue;
      seen.add(variant.id);
      ids.push(variant.id);
    }
    if (!seen.has(group.primary_id)) {
      seen.add(group.primary_id);
      ids.push(group.primary_id);
    }
  }
  return ids;
}

type ReanalyzeHit = {
  document_id: string;
  ok: boolean;
  school_action?: string | null;
  activities?: unknown;
};

export function applyReanalyzeResults<
  T extends {
    id?: string;
    primary_id?: string;
    variants?: Array<{ id: string }>;
    school_action?: string | null;
    activities?: unknown;
  },
>(items: T[], results: ReanalyzeHit[]): T[] {
  const byId = new Map(results.map((r) => [r.document_id, r]));
  return items.map((item) => {
    const candidateIds = [
      item.primary_id,
      item.id,
      ...(item.variants || []).map((v) => v.id),
    ].filter((id): id is string => Boolean(id));
    const hit = candidateIds.map((id) => byId.get(id)).find(Boolean);
    if (!hit) return item;
    const next: T = { ...item };
    if (hit.ok && hit.school_action) {
      next.school_action = hit.school_action;
    }
    if (Array.isArray(hit.activities)) {
      next.activities = hit.activities;
    }
    return next;
  });
}
