"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/Icon";

type Props = {
  fileUrl: string;
  token: string;
};

export default function PdfPreview({ fileUrl, token }: Props) {
  const t = useTranslations("documents");
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pageCount, setPageCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      setLoading(true);
      setError(false);
      setPageCount(0);
      const host = hostRef.current;
      if (!host) return;
      host.replaceChildren();

      try {
        const res = await fetch(fileUrl, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = await res.arrayBuffer();
        if (cancelled) return;

        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

        const pdf = await pdfjs.getDocument({ data }).promise;
        if (cancelled) return;
        setPageCount(pdf.numPages);

        for (let pageNum = 1; pageNum <= pdf.numPages; pageNum += 1) {
          const page = await pdf.getPage(pageNum);
          if (cancelled) return;
          const base = page.getViewport({ scale: 1 });
          const width = Math.min(host.clientWidth || 720, 960);
          const scale = width / base.width;
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement("canvas");
          canvas.className = "pdf-page";
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          const ctx = canvas.getContext("2d");
          if (!ctx) throw new Error("canvas");
          await page.render({ canvasContext: ctx, viewport }).promise;
          if (cancelled) return;
          host.appendChild(canvas);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [fileUrl, token]);

  return (
    <div className="pdf-preview">
      {loading ? (
        <p className="pdf-status">
          <span className="spinner" />
          {t("previewLoading")}
        </p>
      ) : null}
      {error ? (
        <p className="pdf-status error">
          <Icon name="alert-circle" />
          {t("previewFailed")}
        </p>
      ) : null}
      {!loading && !error && pageCount > 0 ? (
        <p className="pdf-status">
          <Icon name="file-text" />
          {t("previewPages", { count: pageCount })}
        </p>
      ) : null}
      <div ref={hostRef} className="pdf-pages" />
    </div>
  );
}
