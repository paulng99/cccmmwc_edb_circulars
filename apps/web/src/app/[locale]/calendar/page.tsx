"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { getCalendarEvents, type CalendarEvent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDate } from "@/lib/date";
import { Icon } from "@/components/Icon";

type LoadState = "loading" | "success" | "error";
type DayGroup = { date: string; events: CalendarEvent[] };

export default function CalendarPage() {
  const t = useTranslations("calendar");
  const { token, ready } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<LoadState>("loading");
  const [days, setDays] = useState<DayGroup[]>([]);

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
        setDays(res.days || []);
        setStatus("success");
      })
      .catch(() => {
        if (cancelled) return;
        setDays([]);
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
                  <li key={`${ev.document_id}-${ev.kind}-${ev.activity_name || ""}-${ev.date}`}>
                    <Link href={`/documents/${ev.document_id}`} className="calendar-row">
                      <span className={`badge ${ev.kind === "start" ? "green" : "amber"}`}>
                        {ev.kind === "start" ? t("kindStart") : t("kindDeadline")}
                      </span>
                      <span className="calendar-row-text">
                        {ev.activity_name ? (
                          <strong>{ev.activity_name}</strong>
                        ) : null}
                        <span className="deadline-doc-title">{ev.document_title}</span>
                      </span>
                    </Link>
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
