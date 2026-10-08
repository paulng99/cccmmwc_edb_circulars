import { Link } from "@/i18n/routing";
import type { CalendarEvent } from "@/lib/api";

type Props = {
  event: CalendarEvent;
  kindLabel: string;
};

/** Google Calendar–style agenda row: kind on the left, title / summary / location on the right. */
export function AgendaEventRow({ event, kindLabel }: Props) {
  const title = event.activity_name || event.document_title;
  const summary = event.summary?.trim() || "";
  const location = event.location?.trim() || "";

  return (
    <Link href={`/documents/${event.document_id}`} className="agenda-row">
      <span className={`agenda-kind badge ${event.kind === "start" ? "green" : "amber"}`}>
        {kindLabel}
      </span>
      <span className="agenda-body">
        <strong className="agenda-title">{title}</strong>
        {summary ? <span className="agenda-summary">{summary}</span> : null}
        {location ? <span className="agenda-location">{location}</span> : null}
      </span>
    </Link>
  );
}
