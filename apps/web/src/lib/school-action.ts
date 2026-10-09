/** System prefix written by the API for AI-generated school-action text. */
export const UNVERIFIED_PREFIX = "未核對";

/** Strip the unverified marker so UI can show an AI icon instead. */
export function displaySchoolAction(text: string | null | undefined): string {
  const raw = (text || "").trim();
  if (!raw) return "";
  if (raw === UNVERIFIED_PREFIX) return "";
  if (raw.startsWith(`${UNVERIFIED_PREFIX}\n`)) {
    return raw.slice(UNVERIFIED_PREFIX.length + 1).trim();
  }
  if (raw.startsWith(UNVERIFIED_PREFIX)) {
    return raw.slice(UNVERIFIED_PREFIX.length).trim();
  }
  return raw;
}
