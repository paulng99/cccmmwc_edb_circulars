"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { CalendarEvent } from "@/lib/api";
import { AgendaEventRow } from "@/components/AgendaEventRow";
import { formatHkDate, hkTodayIso } from "@/lib/date";
import {
  EXTEND_BY_MONTHS,
  INITIAL_FUTURE_MONTHS,
  INITIAL_PAST_MONTHS,
  MONTH_LIMIT,
  SCROLL_EDGE_PX,
  canExtend,
  extendMonths,
  isoInMonth,
  monthKey,
  monthWindow,
  scrollEdge,
  scrollTopAfterPrepend,
  initialScrollTop,
  weekdayIndex,
  weeksForMonth,
  yearMonthFromIso,
  type YearMonth,
} from "@/lib/calendar-month";

const WEEKDAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;

type DayGroup = { date: string; events: CalendarEvent[] };

type Props = {
  days: DayGroup[];
};

function scrollTopForCurrentMonth(scroller: HTMLElement, month: HTMLElement): number {
  const todayEl = month.querySelector<HTMLElement>(".month-day.is-today");
  if (!todayEl) return month.offsetTop;
  const todayTop =
    todayEl.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
  return initialScrollTop(month.offsetTop, todayTop, todayEl.offsetHeight, scroller.clientHeight);
}

function kindMarker(kind: CalendarEvent["kind"]): "start" | "deadline" {
  switch (kind) {
    case "start":
      return "start";
    case "deadline":
      return "deadline";
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

export function MonthCalendar({ days }: Props) {
  const t = useTranslations("calendar");
  const todayIso = hkTodayIso();
  const todayYm = yearMonthFromIso(todayIso) ?? { year: 1970, month: 1 };
  const currentKey = monthKey(todayYm);

  const [months, setMonths] = useState<YearMonth[]>(() =>
    monthWindow(todayYm, INITIAL_PAST_MONTHS, INITIAL_FUTURE_MONTHS),
  );
  const [selected, setSelected] = useState(todayIso);
  const [anchored, setAnchored] = useState(false);
  const [anchorAttempt, setAnchorAttempt] = useState(0);

  const scrollerRef = useRef<HTMLDivElement>(null);
  const monthRefs = useRef(new Map<string, HTMLElement>());
  const monthsRef = useRef(months);
  const anchoredRef = useRef(false);
  const lockRef = useRef(false);
  const pendingPrependHeight = useRef<number | null>(null);
  const anchorTries = useRef(0);
  const navigatingRef = useRef(false);
  monthsRef.current = months;

  const byDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const day of days) map.set(day.date, day.events);
    return map;
  }, [days]);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    if (!anchoredRef.current) {
      const current = monthRefs.current.get(currentKey);
      if (!current || scroller.clientHeight === 0) {
        if (anchorTries.current >= 12) return;
        anchorTries.current += 1;
        const id = requestAnimationFrame(() => setAnchorAttempt((n) => n + 1));
        return () => cancelAnimationFrame(id);
      }
      scroller.scrollTop = scrollTopForCurrentMonth(scroller, current);
      anchoredRef.current = true;
      setAnchored(true);
      return;
    }

    if (pendingPrependHeight.current != null) {
      scroller.scrollTop = scrollTopAfterPrepend(
        scroller.scrollTop,
        pendingPrependHeight.current,
        scroller.scrollHeight,
      );
      pendingPrependHeight.current = null;
    }
    lockRef.current = false;
  }, [months, currentKey, anchorAttempt]);

  const onScroll = () => {
    if (lockRef.current || !anchoredRef.current || navigatingRef.current) return;
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const edge = scrollEdge(
      scroller.scrollTop,
      scroller.scrollHeight,
      scroller.clientHeight,
      SCROLL_EDGE_PX,
    );
    if (edge === "none") return;
    const list = monthsRef.current;
    if (!canExtend(list, edge, todayYm, MONTH_LIMIT)) return;
    if (edge === "prepend") pendingPrependHeight.current = scroller.scrollHeight;
    lockRef.current = true;
    setMonths((current) => {
      if (!canExtend(current, edge, todayYm, MONTH_LIMIT)) {
        pendingPrependHeight.current = null;
        lockRef.current = false;
        return current;
      }
      return extendMonths(current, edge, EXTEND_BY_MONTHS);
    });
  };

  const goToThisMonth = () => {
    setSelected(todayIso);
    const scroller = scrollerRef.current;
    const current = monthRefs.current.get(currentKey);
    if (!scroller || !current) return;
    const top = scrollTopForCurrentMonth(scroller, current);
    if (Math.abs(scroller.scrollTop - top) < 2) return;
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    navigatingRef.current = true;
    const stop = () => {
      navigatingRef.current = false;
    };
    scroller.addEventListener("scrollend", stop, { once: true });
    window.setTimeout(stop, reduce ? 50 : 900);
    scroller.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
  };

  const cancelNavigation = () => {
    navigatingRef.current = false;
  };

  const weekdays = WEEKDAY_KEYS.map((key) => t(`weekdays.${key}`));
  const selectedEvents = byDate.get(selected) ?? [];
  const selectedDow = weekdayIndex(selected);
  const hasAnyEvents = days.some((day) => day.events.length > 0);

  return (
    <div className="month-cal">
      <div className="month-cal-bar">
        <ul className="month-legend">
          <li>
            <i className="month-day-dot start" aria-hidden />
            {t("kindStart")}
          </li>
          <li>
            <i className="month-day-dot deadline" aria-hidden />
            {t("kindDeadline")}
          </li>
        </ul>
        <button type="button" className="btn secondary sm" onClick={goToThisMonth}>
          {t("thisMonth")}
        </button>
      </div>

      <div
        ref={scrollerRef}
        className={anchored ? "month-scroller is-anchored" : "month-scroller"}
        tabIndex={0}
        aria-label={t("scrollMonths")}
        onScroll={onScroll}
        onWheel={cancelNavigation}
        onTouchStart={cancelNavigation}
      >
        {months.map((ym) => {
          const key = monthKey(ym);
          const isCurrent = key === currentKey;
          const weeks = weeksForMonth(ym);
          return (
            <section
              key={key}
              className={isCurrent ? "month-block is-current" : "month-block"}
              data-month={key}
              data-current={isCurrent ? "true" : "false"}
              ref={(node) => {
                if (node) monthRefs.current.set(key, node);
                else monthRefs.current.delete(key);
              }}
            >
              <header className="month-block-head">
                <h2>
                  <time dateTime={key}>{key}</time>
                </h2>
                {isCurrent ? <span className="badge blue">{t("thisMonth")}</span> : null}
              </header>
              <div className="month-weekdays" aria-hidden>
                {weekdays.map((label, index) => (
                  <span
                    key={WEEKDAY_KEYS[index]}
                    className={index === 0 ? "is-sun" : index === 6 ? "is-sat" : undefined}
                  >
                    {label}
                  </span>
                ))}
              </div>
              <div className="month-grid" role="grid" aria-label={key}>
                {weeks.map((week) => (
                  <div key={week[0]} className="month-week" role="row">
                  {week.map((iso) => {
                    const events = byDate.get(iso) ?? [];
                    const dow = weekdayIndex(iso);
                    const outside = !isoInMonth(iso, ym);
                    const markers = Array.from(new Set(events.map((event) => kindMarker(event.kind))));
                    const dayNum = Number(iso.slice(8, 10));
                    const className = [
                      "month-day",
                      outside ? "is-outside" : "",
                      iso === todayIso ? "is-today" : "",
                      iso === selected ? "is-selected" : "",
                      dow === 0 ? "is-sun" : "",
                      dow === 6 ? "is-sat" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");
                    return (
                      <button
                        key={iso}
                        type="button"
                        role="gridcell"
                        className={className}
                        aria-current={iso === todayIso ? "date" : undefined}
                        aria-selected={iso === selected}
                        aria-label={t("dayAria", { date: iso, count: events.length })}
                        onClick={() => setSelected(iso)}
                      >
                        <span className="month-day-num">{dayNum}</span>
                        <span className="month-day-dots">
                          {markers.map((marker) => (
                            <i key={marker} className={`month-day-dot ${marker}`} />
                          ))}
                          {events.length > 1 ? (
                            <span className="month-day-count">{events.length}</span>
                          ) : null}
                        </span>
                      </button>
                    );
                  })}
                  </div>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <section className="month-agenda" aria-live="polite">
        <h2>
          <time dateTime={selected}>{formatHkDate(selected)}</time>
          {selectedDow != null ? (
            <span className="month-agenda-weekday">{weekdays[selectedDow]}</span>
          ) : null}
        </h2>
        {selectedEvents.length > 0 ? (
          <div className="calendar-days">
            <ul>
              {selectedEvents.map((event) => (
                <li
                  key={`${event.document_id}-${event.kind}-${event.activity_name || ""}-${event.date}-${event.summary || ""}`}
                >
                  <AgendaEventRow
                    event={event}
                    kindLabel={event.kind === "start" ? t("kindStart") : t("kindDeadline")}
                  />
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted">{hasAnyEvents ? t("noDayEvents") : t("empty")}</p>
        )}
      </section>
    </div>
  );
}
