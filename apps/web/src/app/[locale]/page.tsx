"use client";

import { useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { getUpcomingDeadlines, type CalendarEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDate } from "@/lib/date";
import { useRefreshingQuery } from "@/lib/useRefreshingQuery";
import { AgendaEventRow } from "@/components/AgendaEventRow";
import { DatesUpdatingCard } from "@/components/DatesUpdatingCard";
import { Icon } from "@/components/Icon";

type DayGroup = { date: string; events: CalendarEvent[] };

function loadHomeDeadlines(token: string) {
  return getUpcomingDeadlines(token, 7);
}

function groupByDate(items: CalendarEvent[]): DayGroup[] {
  const map = new Map<string, CalendarEvent[]>();
  for (const item of items) {
    const list = map.get(item.date) || [];
    list.push(item);
    map.set(item.date, list);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, events]) => ({ date, events }));
}

export default function HomePage() {
  const t = useTranslations("home");
  const { token, ready } = useAuth();
  const router = useRouter();
  const { status, data } = useRefreshingQuery(token, ready, loadHomeDeadlines);
  const datesUpdating = Boolean(data?.dates_updating);
  const items = datesUpdating ? [] : data?.items || [];

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  const days = useMemo(() => groupByDate(items), [items]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="muted">{t("subtitle")}</p>
        </div>
        <Link className="btn secondary sm" href="/calendar">
          <Icon name="calendar" />
          {t("openCalendar")}
        </Link>
      </header>

      {status === "loading" ? (
        <div className="card empty" aria-busy="true">
          <span className="spinner lg" />
          <p>{t("loading")}</p>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="card empty">
          <div className="empty-icon danger">
            <Icon name="alert-triangle" />
          </div>
          <h3>{t("loadError")}</h3>
        </div>
      ) : null}

      {status === "success" && datesUpdating ? (
        <DatesUpdatingCard
          title={t("datesUpdating")}
          progress={data?.dates_progress}
          token={token}
        />
      ) : null}

      {status === "success" && !datesUpdating && days.length === 0 ? (
        <div className="card empty">
          <div className="empty-icon">
            <Icon name="calendar" />
          </div>
          <h3>{t("empty")}</h3>
        </div>
      ) : null}

      {status === "success" && !datesUpdating && days.length > 0 ? (
        <div className="calendar-days">
          {days.map((day) => (
            <section key={day.date} className="calendar-day">
              <h2>
                <time dateTime={day.date}>{formatHkDate(day.date)}</time>
              </h2>
              <ul>
                {day.events.map((ev) => (
                  <li
                    key={`${ev.document_id}-${ev.date}-${ev.activity_name || ""}-${ev.summary || ""}`}
                  >
                    <AgendaEventRow event={ev} kindLabel={t("kindDeadline")} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
