"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { setDatesBackfillPaused, type DatesProgress } from "@/lib/api";
import { Icon } from "@/components/Icon";

export function DatesUpdatingCard({
  title,
  progress,
  token,
}: {
  title: string;
  progress?: DatesProgress | null;
  token: string | null;
}) {
  const t = useTranslations("datesBackfill");
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  const known = total > 0;
  const pct = known ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const countLabel = known ? t("count", { done, total }) : title;
  const serverPaused = Boolean(progress?.paused);
  const [paused, setPaused] = useState(serverPaused);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!pending) setPaused(serverPaused);
  }, [serverPaused, pending]);

  async function toggle() {
    if (!token || pending) return;
    const next = !paused;
    setPaused(next);
    setPending(true);
    try {
      await setDatesBackfillPaused(token, next);
    } catch {
      setPaused(!next);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="card empty" role="status" aria-live="polite">
      <div className="empty-icon">
        <Icon name="calendar" />
      </div>
      <h3>{title}</h3>
      <div className={`dates-backfill${paused ? " is-paused" : ""}`}>
        {known ? <p className="dates-backfill-count">{countLabel}</p> : null}
        <div
          className="progress-track"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={known ? 100 : undefined}
          aria-valuenow={known ? pct : undefined}
          aria-valuetext={countLabel}
          aria-busy={known && !paused ? true : undefined}
        >
          <div
            className={known ? "progress-fill" : "progress-fill indeterminate"}
            style={known ? { width: `${pct}%` } : undefined}
          />
        </div>
        {paused ? <p className="dates-backfill-current">{t("paused")}</p> : null}
        {!paused && progress?.current ? (
          <p className="dates-backfill-current muted">{progress.current}</p>
        ) : null}
        {token ? (
          <button
            type="button"
            className="btn secondary icon-only dates-backfill-toggle"
            aria-label={paused ? t("resume") : t("pause")}
            aria-pressed={paused}
            disabled={pending}
            onClick={() => {
              void toggle();
            }}
          >
            <Icon name={paused ? "play" : "pause"} />
          </button>
        ) : null}
      </div>
    </div>
  );
}
