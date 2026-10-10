"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { getCalendarEvents, type CalendarEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDate } from "@/lib/date";
import { useRefreshingQuery } from "@/lib/useRefreshingQuery";
import { AgendaEventRow } from "@/components/AgendaEventRow";
import { DatesUpdatingCard } from "@/components/DatesUpdatingCard";
import { Icon } from "@/components/Icon";

type DayGroup = { date: string; events: CalendarEvent[] };

function loadCalendar(token: string) {
  return getCalendarEvents(token);
}

export default function CalendarPage() {
  const t = useTranslations("calendar");
  const { token, ready } = useAuth();
  const router = useRouter();
  const { status, data } = useRefreshingQuery(token, ready, loadCalendar);
  const datesUpdating = Boolean(data?.dates_updating);
  const days: DayGroup[] = datesUpdating ? [] : data?.days || [];

  useEffect(() => {
    if (ready && !token) router.replace("/login");
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
