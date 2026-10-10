"use client";

import { useEffect, useRef, useState } from "react";

type LoadState = "loading" | "success" | "error";

const POLL_MS = 2000;

export function useRefreshingQuery<T extends { dates_updating?: boolean }>(
  token: string | null,
  ready: boolean,
  fetcher: (token: string) => Promise<T>,
) {
  const [status, setStatus] = useState<LoadState>("loading");
  const [data, setData] = useState<T | null>(null);
  const hasData = useRef(false);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    let timer: number | undefined;
    hasData.current = false;

    const schedule = () => {
      timer = window.setTimeout(run, POLL_MS);
    };

    const run = () => {
      fetcher(token)
        .then((res) => {
          if (cancelled) return;
          hasData.current = true;
          setData(res);
          setStatus("success");
          if (res.dates_updating) schedule();
        })
        .catch(() => {
          if (cancelled) return;
          if (!hasData.current) {
            setStatus("error");
            return;
          }
          schedule();
        });
    };

    setStatus("loading");
    setData(null);
    run();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [ready, token, fetcher]);

  return { status, data };
}
