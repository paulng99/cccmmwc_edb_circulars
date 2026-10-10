"use client";

import { useTranslations } from "next-intl";
import type { DatesProgress } from "@/lib/api";
import { Icon } from "@/components/Icon";

export function DatesUpdatingCard({
  title,
  progress,
}: {
  title: string;
  progress?: DatesProgress | null;
}) {
  const t = useTranslations("datesBackfill");
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  const known = total > 0;
  const pct = known ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const countLabel = known ? t("count", { done, total }) : title;

  return (
    <div className="card empty" role="status" aria-live="polite">
      <div className="empty-icon">
        <Icon name="calendar" />
      </div>
      <h3>{title}</h3>
      <div className="dates-backfill">
        {known ? <p className="dates-backfill-count">{countLabel}</p> : null}
        <div
          className="progress-track"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={known ? 100 : undefined}
          aria-valuenow={known ? pct : undefined}
          aria-valuetext={countLabel}
          aria-busy={known ? undefined : true}
        >
          <div
            className={known ? "progress-fill" : "progress-fill indeterminate"}
            style={known ? { width: `${pct}%` } : undefined}
          />
        </div>
        {progress?.current ? (
          <p className="dates-backfill-current muted">{progress.current}</p>
        ) : null}
      </div>
    </div>
  );
}
