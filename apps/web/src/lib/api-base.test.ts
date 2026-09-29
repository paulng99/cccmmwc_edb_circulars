import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { resolveApiBase } from "./api.ts";
import { apiOrigins, proxyApiRequest } from "./api-proxy.ts";

test("empty config uses same-origin proxy", () => {
  assert.equal(resolveApiBase(""), "");
  assert.equal(resolveApiBase(undefined), "");
  assert.equal(resolveApiBase("   "), "");
});

test("loopback config is ignored so remote browsers do not call the visitor machine", () => {
  assert.equal(resolveApiBase("http://127.0.0.1:8008"), "");
  assert.equal(resolveApiBase("http://localhost:8008"), "");
  assert.equal(resolveApiBase("http://LOCALHOST:8008/"), "");
  assert.equal(resolveApiBase("http://[::1]:8008"), "");
  assert.equal(resolveApiBase("http://0.0.0.0:8008"), "");
});

test("public API URL is used as-is", () => {
  assert.equal(resolveApiBase("https://api.example.com"), "https://api.example.com");
  assert.equal(resolveApiBase("http://165.245.184.200:8008/"), "http://165.245.184.200:8008");
});

test("docker origin is tried before local fallbacks", () => {
  assert.deepEqual(apiOrigins("http://api:8008"), [
    "http://api:8008",
    "http://127.0.0.1:8008",
    "http://host.docker.internal:8008",
  ]);
  assert.equal(apiOrigins(undefined)[0], "http://127.0.0.1:8008");
});

test("proxy falls back when the first host does not exist", async () => {
  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        url: req.url,
        auth: req.headers.authorization ?? null,
        body: Buffer.concat(chunks).toString(),
      }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as { port: number }).port;
  try {
    const upstream = await proxyApiRequest({
      origins: ["http://no-such-host.invalid:8008", `http://127.0.0.1:${port}`],
      path: "/api/auth/login",
      method: "POST",
      headers: new Headers({ "content-type": "application/json", authorization: "Bearer secret" }),
      body: new TextEncoder().encode('{"username":"admin"}'),
      timeoutMs: 1500,
    });
    assert.equal(upstream.status, 200);
    assert.equal(upstream.origin, `http://127.0.0.1:${port}`);
    const payload = JSON.parse(new TextDecoder().decode(Buffer.from(await new Response(upstream.body).arrayBuffer())));
    assert.equal(payload.url, "/api/auth/login");
    assert.equal(payload.auth, "Bearer secret");
    assert.equal(payload.body, '{"username":"admin"}');
  } finally {
    await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())));
  }
});
