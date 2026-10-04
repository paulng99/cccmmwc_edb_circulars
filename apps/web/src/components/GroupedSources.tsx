"use client";

import { useId, useMemo, type ChangeEvent } from "react";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/Icon";
import type { Citation } from "@/lib/chat-store";
import { groupCitationsByDocument } from "@/lib/group-citations";
import {
  chunkOptionLabel,
  documentLabel,
  singleOptionLabel,
} from "@/lib/source-option-labels";

type Props = {
  citations: Citation[];
  answerContent: string;
  activeRef?: string;
  onOpen: (c: Citation) => void;
  onClose: () => void;
};

export default function GroupedSources({
  citations,
  answerContent,
  activeRef,
  onOpen,
  onClose,
}: Props) {
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
  const selectedTitle = useMemo(() => {
    if (!selected) return t("sourcesSelectPlaceholder");
    for (const group of groups) {
      const chunk = group.chunks.find((c) => c.ref === selected);
      if (!chunk) continue;
      const mergeable = Boolean(group.documentId) && group.chunks.length > 1;
      if (mergeable) {
        return `${documentLabel(group)} · ${chunkOptionLabel(chunk, (index, ref) =>
          t("chunkLabel", { index, ref }),
        )}`;
      }
      return singleOptionLabel(group, chunk);
    }
    return selected;
  }, [groups, selected, t]);

  function onSelect(e: ChangeEvent<HTMLSelectElement>) {
    const value = e.target.value;
    if (!value) {
      onClose();
      return;
    }
    const cite = byRef.get(value);
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
        title={selectedTitle}
      >
        <option value="">{t("sourcesSelectPlaceholder")}</option>
        {groups.map((group) => {
          const mergeable = Boolean(group.documentId) && group.chunks.length > 1;
          if (!mergeable) {
            const primary = group.chunks[0];
            const label = singleOptionLabel(group, primary);
            return (
              <option key={group.key} value={primary.ref} title={label}>
                {label}
              </option>
            );
          }
          const groupLabel = documentLabel(group);
          return (
            <optgroup key={group.key} label={groupLabel}>
              {group.chunks.map((chunk) => {
                const label = chunkOptionLabel(chunk, (index, ref) =>
                  t("chunkLabel", { index, ref }),
                );
                return (
                  <option key={chunk.ref} value={chunk.ref} title={`${groupLabel} · ${label}`}>
                    {label}
                  </option>
                );
              })}
            </optgroup>
          );
        })}
      </select>
    </div>
  );
}
