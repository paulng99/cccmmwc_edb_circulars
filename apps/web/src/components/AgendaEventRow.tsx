import { Link } from "@/i18n/routing";
import type { CalendarEvent } from "@/lib/api";

type Props = {
  event: CalendarEvent;
  kindLabel: string;
};

/**
 * Google Calendar–style agenda row: kind on the left; title, optional circular
 * title (smaller), optional summary, optional location on the right.
 * Missing summary/location omit those lines (no blank placeholders).
 */
export function AgendaEventRow({ event, kindLabel }: Props) {
  const itemTitle =
    event.activity_name?.trim() ||
    (event.kind === "deadline" ? "交回文件" : event.document_title);
  const docTitle = event.document_title?.trim() || "";
  const showDocTitle = Boolean(docTitle) && docTitle !== itemTitle;
  const summary = event.summary?.trim() || "";
  const location = event.location?.trim() || "";

  return (
    <Link href={`/documents/${event.document_id}`} className="agenda-row">
      <span className={`agenda-kind badge ${event.kind === "start" ? "green" : "amber"}`}>
        {kindLabel}
      </span>
      <span className="agenda-body">
        <strong className="agenda-title">{itemTitle}</strong>
        {showDocTitle ? <span className="agenda-doc-title">{docTitle}</span> : null}
        {summary ? <span className="agenda-summary">{summary}</span> : null}
        {location ? <span className="agenda-location">{location}</span> : null}
      </span>
    </Link>
  );
}
