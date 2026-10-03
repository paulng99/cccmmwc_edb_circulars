"use client";

import { useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "@/lib/chat-store";
import {
  chatUrlTransform,
  citationRefFromHref,
  isSafeExternalHref,
  linkifyCitationRefs,
} from "@/lib/cite-markdown";

type Props = {
  content: string;
  citations?: Citation[];
  activeRef?: string;
  onOpen: (c: Citation) => void;
};

export default function AssistantMarkdown({ content, citations, activeRef, onOpen }: Props) {
  const byRef = useMemo(() => new Map((citations || []).map((c) => [String(c.ref), c])), [citations]);
  const markdown = useMemo(() => linkifyCitationRefs(content, citations), [content, citations]);

  return (
    <div className="md-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={chatUrlTransform}
        components={{
          a: ({ href, children }) => {
            const ref = citationRefFromHref(href);
            if (ref) {
              const cite = byRef.get(ref);
              if (!cite) return <>{`[${ref}]`}</>;
              return (
                <button
                  type="button"
                  className={`cite-ref${activeRef === cite.ref ? " active" : ""}`}
                  title={cite.title || ref}
                  onClick={() => onOpen(cite)}
                >
                  {ref}
                </button>
              );
            }
            if (!isSafeExternalHref(href)) {
              return <span>{children}</span>;
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
          // Never render raw HTML nodes even if a future plugin introduces them.
          script: () => null,
          iframe: () => null,
          img: ({ alt }) => <span>{alt || ""}</span>,
          table: ({ children }) => (
            <div className="md-table-wrap">
              <table>{children}</table>
            </div>
          ),
          code: ({ className, children, ...props }) => {
            const text = String(children).replace(/\n$/, "");
            const isBlock = Boolean(className) || text.includes("\n");
            if (isBlock) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            }
            return (
              <code className="md-inline-code" {...props}>
                {children}
              </code>
            );
          },
          p: ({ children }) => <p>{children as ReactNode}</p>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
