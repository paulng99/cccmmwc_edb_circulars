import http from "node:http";
import https from "node:https";
import { lookup } from "node:dns";
import { Readable } from "node:stream";

const DEFAULT_ORIGINS = ["http://api:8008", "http://127.0.0.1:8008", "http://host.docker.internal:8008"];

/** Ordered upstream bases. A configured URL is tried first, then the usual Docker and local addresses. */
export function apiOrigins(envValue?: string | null): string[] {
  const configured = (envValue ?? "").trim().replace(/\/$/, "");
  const list = configured
    ? [configured, ...DEFAULT_ORIGINS]
    : ["http://127.0.0.1:8008", ...DEFAULT_ORIGINS];
  return [...new Set(list)];
}

const SKIP_REQUEST_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

const SKIP_RESPONSE_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);

export type ProxyFailure = { host: string; reason: string };

export class ApiProxyError extends Error {
  host: string;
  reason: string;
  constructor(failure: ProxyFailure) {
    super("api_unreachable");
    this.name = "ApiProxyError";
    this.host = failure.host;
    this.reason = failure.reason;
  }
}

function hostLabel(origin: string): string {
  try {
    const url = new URL(origin);
    return url.host;
  } catch {
    return origin;
  }
}

function lookup4(hostname: string, timeoutMs: number): Promise<string> {
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(hostname)) return Promise.resolve(hostname);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(Object.assign(new Error("timeout"), { code: "timeout" }));
    }, timeoutMs);
    lookup(hostname, { family: 4 }, (err, address) => {
      clearTimeout(timer);
      if (err || !address) reject(err ?? Object.assign(new Error("ENOTFOUND"), { code: "ENOTFOUND" }));
      else resolve(address);
    });
  });
}

function requestOnce(
  origin: string,
  path: string,
  method: string,
  headers: http.OutgoingHttpHeaders,
  body: Uint8Array | undefined,
  timeoutMs: number,
): Promise<{ status: number; headers: http.IncomingHttpHeaders; stream: http.IncomingMessage }> {
  const url = new URL(path, `${origin}/`);
  const lib = url.protocol === "https:" ? https : http;
  return lookup4(url.hostname, timeoutMs).then(
    (address) =>
      new Promise((resolve, reject) => {
        const req = lib.request(
          {
            host: address,
            port: url.port || (url.protocol === "https:" ? 443 : 80),
            path: `${url.pathname}${url.search}`,
            method,
            headers: { ...headers, host: url.host },
            family: 4,
          },
          (res) => {
            req.setTimeout(0);
            resolve({ status: res.statusCode || 502, headers: res.headers, stream: res });
          },
        );
        const fail = (err: Error) => {
          req.destroy();
          reject(err);
        };
        req.setTimeout(timeoutMs, () => fail(Object.assign(new Error("timeout"), { code: "timeout" })));
        req.on("error", reject);
        if (body && body.byteLength) req.end(body);
        else req.end();
      }),
  );
}

function toHeaders(incoming: http.IncomingHttpHeaders): Headers {
  const out = new Headers();
  for (const [key, value] of Object.entries(incoming)) {
    if (!value || SKIP_RESPONSE_HEADERS.has(key.toLowerCase())) continue;
    if (Array.isArray(value)) {
      for (const item of value) out.append(key, item);
    } else {
      out.set(key, value);
    }
  }
  return out;
}

export async function proxyApiRequest(opts: {
  origins: string[];
  path: string;
  method: string;
  headers: Headers;
  body?: Uint8Array;
  timeoutMs?: number;
  forwardedHost?: string | null;
  forwardedProto?: string | null;
}): Promise<{ status: number; headers: Headers; body: ReadableStream<Uint8Array> | null; origin: string }> {
  const timeoutMs = opts.timeoutMs ?? 2500;
  const headers: http.OutgoingHttpHeaders = {};
  opts.headers.forEach((value, key) => {
    if (!SKIP_REQUEST_HEADERS.has(key.toLowerCase())) headers[key] = value;
  });
  if (opts.forwardedHost) headers["x-forwarded-host"] = opts.forwardedHost;
  if (opts.forwardedProto) headers["x-forwarded-proto"] = opts.forwardedProto;
  if (opts.body) headers["content-length"] = String(opts.body.byteLength);

  const failures: string[] = [];
  for (const origin of opts.origins) {
    try {
      const upstream = await requestOnce(origin, opts.path, opts.method, headers, opts.body, timeoutMs);
      const body = Readable.toWeb(upstream.stream) as ReadableStream<Uint8Array>;
      return { status: upstream.status, headers: toHeaders(upstream.headers), body, origin };
    } catch (err) {
      const code = err && typeof err === "object" && "code" in err ? String((err as { code?: string }).code) : "fetch_failed";
      failures.push(`${hostLabel(origin)} ${code || "fetch_failed"}`);
    }
  }
  throw new ApiProxyError({ host: hostLabel(opts.origins[0] || "API"), reason: failures.join("; ") || "unreachable" });
}
