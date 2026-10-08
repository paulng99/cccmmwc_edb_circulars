import type { Citation } from "@/lib/chat-snapshot";

export const CITE_PROTOCOL = "citation:";

export const CITE_REF_SOURCE = String.raw`\[((?:L|D|W)?\d+)\]`;

const CITE_TOKEN = new RegExp(CITE_REF_SOURCE, "g");

/** Turn known `[L1]` tokens into markdown links so react-markdown can render buttons. */
export function linkifyCitationRefs(content: string, citations: Citation[] | undefined): string {
  if (!citations || citations.length === 0) return content;
  const byRef = new Set(citations.map((c) => String(c.ref)));
  return content.replace(CITE_TOKEN, (full, ref: string) => {
    if (!byRef.has(ref)) return full;
    return `[${ref}](${CITE_PROTOCOL}${ref})`;
  });
}

export function citationRefFromHref(href: string | undefined | null): string | null {
  if (!href || !href.startsWith(CITE_PROTOCOL)) return null;
  return href.slice(CITE_PROTOCOL.length) || null;
}

/** Allow citation: plus the safe protocols used for ordinary links. */
export function chatUrlTransform(url: string): string {
  if (url.startsWith(CITE_PROTOCOL)) return url;
  const colon = url.indexOf(":");
  if (colon === -1) return url;
  const protocol = url.slice(0, colon).toLowerCase();
  if (protocol === "http" || protocol === "https" || protocol === "mailto") return url;
  return "";
}

export function isSafeExternalHref(href: string | undefined | null): boolean {
  if (!href) return false;
  const colon = href.indexOf(":");
  if (colon === -1) return href.startsWith("/") || href.startsWith("#");
  const protocol = href.slice(0, colon).toLowerCase();
  return protocol === "http" || protocol === "https" || protocol === "mailto";
}
