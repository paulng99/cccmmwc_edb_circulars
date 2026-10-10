import type { DocumentActivity } from "@/lib/api";

/** Date fields to show for an activity — omit nulls (no「未有」placeholder). */
export function activityDateRows(
  act: Pick<DocumentActivity, "starts_at" | "deadline_at">,
): Array<{ kind: "start" | "deadline"; value: string }> {
  const rows: Array<{ kind: "start" | "deadline"; value: string }> = [];
  if (act.starts_at) {
    rows.push({ kind: "start", value: act.starts_at });
  }
  if (act.deadline_at) {
    rows.push({ kind: "deadline", value: act.deadline_at });
  }
  return rows;
}
