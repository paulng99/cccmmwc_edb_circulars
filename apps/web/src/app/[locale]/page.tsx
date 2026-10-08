"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { getUpcomingDeadlines, type CalendarEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDate } from "@/lib/date";
import { AgendaEventRow } from "@/components/AgendaEventRow";
import { Icon } from "@/components/Icon";

type LoadState = "loading" | "success" | "error";
type DayGroup = { date: string; events: CalendarEvent[] };

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
  const [status, setStatus] = useState<LoadState>("loading");
  const [items, setItems] = useState<CalendarEvent[]>([]);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    getUpcomingDeadlines(token, 7)
      .then((res) => {
        if (cancelled) return;
        setItems(res.items || []);
        setStatus("success");
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
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

      {status === "success" && days.length === 0 ? (
        <div className="card empty">
          <div className="empty-icon">
            <Icon name="calendar" />
          </div>
          <h3>{t("empty")}</h3>
        </div>
      ) : null}

      {status === "success" && days.length > 0 ? (
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
