import type { Citation } from "@/lib/chat-snapshot";

export type SourceGroup = {
  key: string;
  documentId?: string;
  title: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_url?: string;
  backend?: string;
  chunks: Citation[];
};

const REF_IN_TEXT = /\[((?:L|D)?\d+)\]/g;

function firstRefOrder(content: string): Map<string, number> {
  const order = new Map<string, number>();
  let match: RegExpExecArray | null;
  const re = new RegExp(REF_IN_TEXT.source, "g");
  while ((match = re.exec(content)) !== null) {
    const ref = match[1];
    if (!order.has(ref)) order.set(ref, order.size);
  }
  return order;
}

/**
 * Group local citations by document_id. Items without document_id (e.g. Dify)
 * stay as single-item groups. Order follows first appearance of any chunk ref
 * in the answer; uncited documents keep original retrieval order at the end.
 */
export function groupCitationsByDocument(
  citations: Citation[] | undefined,
  answerContent: string,
): SourceGroup[] {
  if (!citations || citations.length === 0) return [];

  const refOrder = firstRefOrder(answerContent || "");
  const groups: SourceGroup[] = [];
  const byDoc = new Map<string, SourceGroup>();

  for (const cite of citations) {
    const docId = cite.document_id?.trim();
    if (!docId) {
      groups.push({
        key: `solo-${cite.ref}`,
        documentId: undefined,
        title: cite.title || cite.ref,
        circular_no: cite.circular_no,
        issued_at: cite.issued_at,
        source_url: cite.source_url,
        backend: cite.backend,
        chunks: [cite],
      });
      continue;
    }
    let group = byDoc.get(docId);
    if (!group) {
      group = {
        key: `doc-${docId}`,
        documentId: docId,
        title: cite.title || cite.ref,
        circular_no: cite.circular_no,
        issued_at: cite.issued_at,
        source_url: cite.source_url,
        backend: cite.backend,
        chunks: [],
      };
      byDoc.set(docId, group);
      groups.push(group);
    }
    group.chunks.push(cite);
  }

  const groupFirstRefIndex = (group: SourceGroup): number => {
    let best = Number.POSITIVE_INFINITY;
    for (const chunk of group.chunks) {
      const idx = refOrder.get(String(chunk.ref));
      if (idx !== undefined && idx < best) best = idx;
    }
    return best;
  };

  const originalIndex = new Map(groups.map((g, i) => [g.key, i]));

  return [...groups].sort((a, b) => {
    const ai = groupFirstRefIndex(a);
    const bi = groupFirstRefIndex(b);
    const aCited = Number.isFinite(ai);
    const bCited = Number.isFinite(bi);
    if (aCited && bCited && ai !== bi) return ai - bi;
    if (aCited !== bCited) return aCited ? -1 : 1;
    return (originalIndex.get(a.key) ?? 0) - (originalIndex.get(b.key) ?? 0);
  });
}
