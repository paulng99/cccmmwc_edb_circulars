export type Theme = "light" | "dark";

/** Resolve preference: explicit storage wins; otherwise system scheme. */
export function resolveTheme(
  stored: string | null | undefined,
  prefersDark: boolean,
): Theme {
  if (stored === "dark" || stored === "light") return stored;
  return prefersDark ? "dark" : "light";
}
