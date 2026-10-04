"use client";

import { ChangeEvent, useId, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/Icon";
import type { Citation } from "@/lib/chat-store";
import { groupCitationsByDocument, type SourceGroup } from "@/lib/group-citations";

type Props = {
  citations: Citation[];
  answerContent: string;
  activeRef?: string;
  onOpen: (c: Citation) => void;
};

function sourceOptionLabel(group: SourceGroup, chunk: Citation, passage?: string): string {
  const parts = [chunk.ref, group.title || "—"];
  if (group.circular_no) parts.push(group.circular_no);
  if (group.issued_at) parts.push(group.issued_at);
  if (passage) parts.push(passage);
  return parts.join(" · ");
}

export default function GroupedSources({ citations, answerContent, activeRef, onOpen }: Props) {
  const t = useTranslations("chat");
  const selectId = useId();
  const groups = useMemo(
    () => groupCitationsByDocument(citations, answerContent),
    [citations, answerContent],
  );
  const byRef = useMemo(() => {
    const map = new Map<string, Citation>();
    for (const c of citations) map.set(c.ref, c);
    return map;
  }, [citations]);

  const selected = activeRef && byRef.has(activeRef) ? activeRef : "";

  function onSelect(e: ChangeEvent<HTMLSelectElement>) {
    const cite = byRef.get(e.target.value);
    if (cite) onOpen(cite);
  }

  return (
    <div className="sources">
      <label className="sources-head" htmlFor={selectId}>
        <Icon name="quote" />
        {t("sourcesCount", { count: groups.length })}
      </label>
      <select
        id={selectId}
        className="select sources-select"
        value={selected}
        onChange={onSelect}
      >
        <option value="">{t("sourcesSelectPlaceholder")}</option>
        {groups.map((group) => {
          const mergeable = Boolean(group.documentId) && group.chunks.length > 1;
          if (!mergeable) {
            const primary = group.chunks[0];
            return (
              <option key={group.key} value={primary.ref}>
                {sourceOptionLabel(group, primary)}
              </option>
            );
          }
          return (
            <optgroup key={group.key} label={group.title || group.key}>
              {group.chunks.map((chunk) => (
                <option key={chunk.ref} value={chunk.ref}>
                  {sourceOptionLabel(
                    group,
                    chunk,
                    typeof chunk.chunk_index === "number"
                      ? t("chunkLabel", { index: chunk.chunk_index + 1, ref: chunk.ref })
                      : undefined,
                  )}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
    </div>
  );
}
