"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { getCalendarEvents, type CalendarEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDate } from "@/lib/date";
import { AgendaEventRow } from "@/components/AgendaEventRow";
import { Icon } from "@/components/Icon";

type LoadState = "loading" | "success" | "error";
type DayGroup = { date: string; events: CalendarEvent[] };

export default function CalendarPage() {
  const t = useTranslations("calendar");
  const { token, ready } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<LoadState>("loading");
  const [days, setDays] = useState<DayGroup[]>([]);
  const [datesUpdating, setDatesUpdating] = useState(false);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    getCalendarEvents(token)
      .then((res) => {
        if (cancelled) return;
        setDatesUpdating(Boolean(res.dates_updating));
        setDays(res.dates_updating ? [] : res.days || []);
        setStatus("success");
      })
      .catch(() => {
        if (cancelled) return;
        setDays([]);
        setDatesUpdating(false);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [ready, token, router]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="muted">{t("subtitle")}</p>
        </div>
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
        <div className="card empty" role="status">
          <div className="empty-icon">
            <Icon name="calendar" />
          </div>
          <h3>{t("datesUpdating")}</h3>
        </div>
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
                    key={`${ev.document_id}-${ev.kind}-${ev.activity_name || ""}-${ev.date}-${ev.summary || ""}`}
                  >
                    <AgendaEventRow
                      event={ev}
                      kindLabel={ev.kind === "start" ? t("kindStart") : t("kindDeadline")}
                    />
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
