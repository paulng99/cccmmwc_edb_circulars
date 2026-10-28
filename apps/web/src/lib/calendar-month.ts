/** Month is 1–12. Week grids start on Sunday (Hong Kong). */
export type YearMonth = {
  year: number;
  month: number;
};

export const INITIAL_PAST_MONTHS = 8;
export const INITIAL_FUTURE_MONTHS = 8;
export const EXTEND_BY_MONTHS = 4;
export const SCROLL_EDGE_PX = 160;
/** How far the scroller may grow from the current month in either direction. */
export const MONTH_LIMIT = 120;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function parseIsoDate(iso: string): { year: number; month: number; day: number } | null {
  const match = ISO_DATE.exec(iso);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const utc = new Date(Date.UTC(year, month - 1, day));
  if (utc.getUTCFullYear() !== year || utc.getUTCMonth() !== month - 1 || utc.getUTCDate() !== day) {
    return null;
  }
  return { year, month, day };
}

export function monthKey(ym: YearMonth): string {
  return `${String(ym.year).padStart(4, "0")}-${String(ym.month).padStart(2, "0")}`;
}

export function yearMonthFromIso(iso: string): YearMonth | null {
  const parsed = parseIsoDate(iso);
  if (!parsed) return null;
  return { year: parsed.year, month: parsed.month };
}

export function shiftMonth(ym: YearMonth, delta: number): YearMonth {
  const index = ym.year * 12 + (ym.month - 1) + delta;
  const year = Math.floor(index / 12);
  const month = index - year * 12 + 1;
  return { year, month };
}

/** Signed month distance from `from` to `to` (positive when `to` is later). */
export function monthsBetween(from: YearMonth, to: YearMonth): number {
  return (to.year - from.year) * 12 + (to.month - from.month);
}

/**
 * Months centred on `center`, with `past` months before it and `future` after.
 * Index `past` is the centre month — the one the calendar opens on.
 */
export function monthWindow(center: YearMonth, past: number, future: number): YearMonth[] {
  const start = shiftMonth(center, -past);
  const total = past + 1 + future;
  return Array.from({ length: total }, (_, index) => shiftMonth(start, index));
}

export function extendMonths(
  months: YearMonth[],
  edge: "prepend" | "append",
  count: number,
): YearMonth[] {
  if (months.length === 0 || count <= 0) return months;
  switch (edge) {
    case "prepend": {
      const start = shiftMonth(months[0], -count);
      const added = Array.from({ length: count }, (_, index) => shiftMonth(start, index));
      return [...added, ...months];
    }
    case "append": {
      const last = months[months.length - 1];
      const added = Array.from({ length: count }, (_, index) => shiftMonth(last, index + 1));
      return [...months, ...added];
    }
    default: {
      const exhaustive: never = edge;
      return exhaustive;
    }
  }
}

export function canExtend(
  months: YearMonth[],
  edge: "prepend" | "append",
  today: YearMonth,
  limit = MONTH_LIMIT,
): boolean {
  if (months.length === 0) return false;
  switch (edge) {
    case "prepend":
      return -monthsBetween(today, months[0]) < limit;
    case "append":
      return monthsBetween(today, months[months.length - 1]) < limit;
    default: {
      const exhaustive: never = edge;
      return exhaustive;
    }
  }
}

export type ScrollEdge = "prepend" | "append" | "none";

/** Which edge is close enough to load more months. No-op when the list does not overflow. */
export function scrollEdge(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  threshold = SCROLL_EDGE_PX,
): ScrollEdge {
  if (clientHeight <= 0 || scrollHeight <= clientHeight + 1) return "none";
  if (scrollTop <= threshold) return "prepend";
  const remaining = scrollHeight - scrollTop - clientHeight;
  if (remaining <= threshold) return "append";
  return "none";
}

/** Keep the month pinned to the top unless today would sit below the visible area. */
export function initialScrollTop(
  monthTop: number,
  todayTop: number,
  todayHeight: number,
  clientHeight: number,
  padding = 8,
): number {
  if (clientHeight <= 0) return monthTop;
  const todayBottom = todayTop + todayHeight;
  if (todayBottom <= monthTop + clientHeight) return monthTop;
  return Math.max(monthTop, todayBottom - clientHeight + padding);
}

/** Keep the same months on screen after older months are inserted above. */
export function scrollTopAfterPrepend(
  scrollTop: number,
  previousHeight: number,
  nextHeight: number,
): number {
  return scrollTop + (nextHeight - previousHeight);
}

/** Sunday-first weeks covering `ym`, including leading and trailing days from neighbours. */
export function weeksForMonth(ym: YearMonth): string[][] {
  const first = new Date(Date.UTC(ym.year, ym.month - 1, 1));
  const cursor = new Date(first);
  cursor.setUTCDate(1 - first.getUTCDay());
  const thisIndex = ym.year * 12 + (ym.month - 1);
  const weeks: string[][] = [];
  while (weeks.length < 6) {
    const week: string[] = [];
    for (let day = 0; day < 7; day += 1) {
      week.push(isoFromUtc(cursor));
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    weeks.push(week);
    const cursorIndex = cursor.getUTCFullYear() * 12 + cursor.getUTCMonth();
    if (cursorIndex > thisIndex) break;
  }
  return weeks;
}

export function isoInMonth(iso: string, ym: YearMonth): boolean {
  return iso.startsWith(`${monthKey(ym)}-`);
}

/** 0 = Sunday … 6 = Saturday. */
export function weekdayIndex(iso: string): number | null {
  const parsed = parseIsoDate(iso);
  if (!parsed) return null;
  return new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day)).getUTCDay();
}

function isoFromUtc(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
