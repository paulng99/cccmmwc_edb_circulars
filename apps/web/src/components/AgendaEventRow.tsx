import { Link } from "@/i18n/routing";
import type { CalendarEvent } from "@/lib/api";
import { agendaTitleLines } from "@/lib/agenda-title";

type Props = {
  event: CalendarEvent;
  kindLabel: string;
};

/**
 * Google Calendar–style agenda row: kind on the left; two-line title (item then
 * notice, same size), optional summary, optional location on the right.
 * Missing summary/location omit those lines (no blank placeholders).
 */
export function AgendaEventRow({ event, kindLabel }: Props) {
  const titleLines = agendaTitleLines(event.activity_name, event.document_title);
  const summary = event.summary?.trim() || "";
  const location = event.location?.trim() || "";

  return (
    <Link href={`/documents/${event.document_id}`} className="agenda-row">
      <span className={`agenda-kind badge ${event.kind === "start" ? "green" : "amber"}`}>
        {kindLabel}
      </span>
      <span className="agenda-body">
        {titleLines.map((line) => (
          <strong key={line} className="agenda-title">
            {line}
          </strong>
        ))}
        {summary ? <span className="agenda-summary">{summary}</span> : null}
        {location ? <span className="agenda-location">{location}</span> : null}
      </span>
    </Link>
  );
}
