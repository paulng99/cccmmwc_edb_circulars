"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import PdfPreview from "@/components/PdfPreview";
import { Icon } from "@/components/Icon";
import { apiBase, fileUrl } from "@/lib/api";

type Props = {
  token: string;
  title: string;
  documentId?: string;
  sourceUrl?: string;
  circularNo?: string | null;
  issuedAt?: string | null;
  onClose: () => void;
};

type DocMeta = {
  title: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_url?: string;
};

export default function ChatDocPanel({
  token,
  title,
  documentId,
  sourceUrl,
  circularNo,
  issuedAt,
  onClose,
}: Props) {
  const t = useTranslations("chat");
  const [meta, setMeta] = useState<DocMeta | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!documentId) {
      setMeta(null);
      setFailed(false);
      return;
    }
    let cancelled = false;
    setFailed(false);
    setMeta(null);
    fetch(`${apiBase()}/api/documents/${documentId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("detail_failed");
        return (await res.json()) as DocMeta;
      })
      .then((data) => {
        if (!cancelled) setMeta(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, token]);

  const heading = meta?.title || title;
  const circ = meta?.circular_no ?? circularNo;
  const issued = meta?.issued_at ?? issuedAt;
  const external = meta?.source_url || sourceUrl;

  return (
    <aside className="chat-doc-panel" aria-label={t("previewTitle")}>
      <header className="chat-doc-head">
        <div className="chat-doc-heading">
          <span className="chat-doc-kicker">
            <Icon name="file-text" />
            {t("previewTitle")}
          </span>
          <h2>{heading}</h2>
          <p className="chat-doc-meta">
            {circ ? (
              <span>
                <Icon name="hash" /> {circ}
              </span>
            ) : null}
            {issued ? (
              <span>
                <Icon name="calendar" /> {issued}
              </span>
            ) : null}
          </p>
        </div>
        <button type="button" className="btn secondary sm icon-only" onClick={onClose} aria-label={t("previewClose")}>
          <Icon name="x" />
        </button>
      </header>
      <div className="chat-doc-scroll">
        {documentId && !failed ? <PdfPreview fileUrl={fileUrl(documentId)} token={token} /> : null}
        {documentId && failed ? <p className="msg-note">{t("previewFailed")}</p> : null}
        {!documentId ? <p className="msg-note">{t("previewExternal")}</p> : null}
      </div>
      <footer className="chat-doc-foot">
        <button type="button" className="btn secondary sm" onClick={onClose}>
          <Icon name="corner-down-left" />
          <span>{t("previewClose")}</span>
        </button>
        {documentId ? (
          <Link href={`/documents/${documentId}`} className="btn ghost sm">
            <Icon name="external-link" />
            <span>{t("previewOpenPage")}</span>
          </Link>
        ) : null}
        {external ? (
          <a href={external} target="_blank" rel="noreferrer" className="btn ghost sm">
            <Icon name="external-link" />
            <span>{t("openOriginal")}</span>
          </a>
        ) : null}
      </footer>
    </aside>
  );
}
