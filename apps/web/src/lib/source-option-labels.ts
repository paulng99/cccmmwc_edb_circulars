import type { Citation } from "@/lib/chat-snapshot";
import type { SourceGroup } from "@/lib/group-citations";

export function documentLabel(group: SourceGroup): string {
  const parts = [group.title || "—"];
  if (group.circular_no) parts.push(group.circular_no);
  return parts.join(" · ");
}

export function singleOptionLabel(group: SourceGroup, chunk: Citation): string {
  const parts = [chunk.ref, group.title || "—"];
  if (group.circular_no) parts.push(group.circular_no);
  return parts.join(" · ");
}

export function chunkOptionLabel(
  chunk: Citation,
  formatPassage: (index: number, ref: string) => string,
): string {
  if (typeof chunk.chunk_index === "number") {
    return formatPassage(chunk.chunk_index + 1, chunk.ref);
  }
  return chunk.ref;
}
