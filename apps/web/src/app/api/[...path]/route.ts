import { NextRequest, NextResponse } from "next/server";
import { ApiProxyError, apiOrigins, proxyApiRequest } from "@/lib/api-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 300;

let preferredOrigin: string | null = null;

async function proxy(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const suffix = `/api/${path.map((segment) => encodeURIComponent(segment)).join("/")}${req.nextUrl.search}`;
  const origins = apiOrigins(process.env.API_INTERNAL_URL);
  const ordered = preferredOrigin && origins.includes(preferredOrigin)
    ? [preferredOrigin, ...origins.filter((origin) => origin !== preferredOrigin)]
    : origins;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  try {
    const upstream = await proxyApiRequest({
      origins: ordered,
      path: suffix,
      method: req.method,
      headers: req.headers,
      body: hasBody ? new Uint8Array(await req.arrayBuffer()) : undefined,
      forwardedHost: req.headers.get("host"),
      forwardedProto: req.nextUrl.protocol.replace(":", ""),
    });
    preferredOrigin = upstream.origin;
    return new Response(upstream.body, { status: upstream.status, headers: upstream.headers });
  } catch (err) {
    const failure = err instanceof ApiProxyError ? err : new ApiProxyError({ host: "API", reason: "unreachable" });
    console.error(`API proxy failed: ${failure.host} ${failure.reason}`);
    if (preferredOrigin === failure.host || preferredOrigin?.includes(failure.host)) preferredOrigin = null;
    return NextResponse.json(
      { detail: "api_unreachable", host: failure.host, reason: failure.reason },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
export const HEAD = proxy;
