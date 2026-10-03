"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/Icon";
import type { Citation } from "@/lib/chat-store";
import { groupCitationsByDocument } from "@/lib/group-citations";

type Props = {
  citations: Citation[];
  answerContent: string;
  activeRef?: string;
  onOpen: (c: Citation) => void;
};

export default function GroupedSources({ citations, answerContent, activeRef, onOpen }: Props) {
  const t = useTranslations("chat");
  const groups = useMemo(
    () => groupCitationsByDocument(citations, answerContent),
    [citations, answerContent],
  );
  const [openKeys, setOpenKeys] = useState<Set<string>>(() => new Set());

  function toggle(key: string) {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="sources">
      <span className="sources-head">
        <Icon name="quote" />
        {t("sourcesCount", { count: groups.length })}
      </span>
      <div className="source-grid">
        {groups.map((group) => {
          const primary = group.chunks[0];
          const mergeable = Boolean(group.documentId);
          const groupActive = group.chunks.some((c) => c.ref === activeRef);

          if (!mergeable) {
            return (
              <button
                key={group.key}
                type="button"
                className={`source-card${activeRef === primary.ref ? " active" : ""}`}
                onClick={() => onOpen(primary)}
              >
                <span className="source-num">{primary.ref}</span>
                <span className="source-body">
                  <span className="source-title">{group.title || "—"}</span>
                  <span className="source-meta">
                    {group.circular_no ? (
                      <span>
                        <Icon name="hash" /> {group.circular_no}
                      </span>
                    ) : null}
                    {group.issued_at ? (
                      <span>
                        <Icon name="calendar" /> {group.issued_at}
                      </span>
                    ) : null}
                    {group.backend && group.backend !== "local" ? (
                      <span className="badge sky">{group.backend}</span>
                    ) : null}
                  </span>
                </span>
              </button>
            );
          }

          const expanded = openKeys.has(group.key);
          return (
            <div key={group.key} className={`source-group${groupActive ? " active" : ""}`}>
              <div className="source-group-head">
                <button
                  type="button"
                  className="source-group-main"
                  onClick={() => onOpen(primary)}
                  title={group.title || primary.ref}
                >
                  <span className="source-num">
                    {group.chunks.length === 1 ? primary.ref : group.chunks.length}
                  </span>
                  <span className="source-body">
                    <span className="source-title">{group.title || "—"}</span>
                    <span className="source-meta">
                      {group.circular_no ? (
                        <span>
                          <Icon name="hash" /> {group.circular_no}
                        </span>
                      ) : null}
                      {group.issued_at ? (
                        <span>
                          <Icon name="calendar" /> {group.issued_at}
                        </span>
                      ) : null}
                      <span className="source-chunk-count">
                        {t("citedChunks", { count: group.chunks.length })}
                      </span>
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  className="btn ghost icon-only sm source-group-toggle"
                  aria-expanded={expanded}
                  aria-label={expanded ? t("collapseChunks") : t("expandChunks")}
                  onClick={() => toggle(group.key)}
                >
                  <Icon name={expanded ? "chevron-up" : "chevron-down"} />
                </button>
              </div>
              {expanded ? (
                <div className="source-chunk-list">
                  {group.chunks.map((chunk) => (
                    <button
                      key={chunk.ref}
                      type="button"
                      className={`source-chunk${activeRef === chunk.ref ? " active" : ""}`}
                      onClick={() => onOpen(chunk)}
                    >
                      <span className="source-num">{chunk.ref}</span>
                      <span className="source-chunk-label">
                        {typeof chunk.chunk_index === "number"
                          ? t("chunkLabel", { index: chunk.chunk_index + 1, ref: chunk.ref })
                          : chunk.ref}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
