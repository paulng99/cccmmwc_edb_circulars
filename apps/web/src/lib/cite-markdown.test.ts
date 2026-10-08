import assert from "node:assert/strict";
import test from "node:test";
import {
  chatUrlTransform,
  citationRefFromHref,
  isSafeExternalHref,
  linkifyCitationRefs,
} from "./cite-markdown.ts";
import type { Citation } from "./chat-snapshot.ts";

const cites: Citation[] = [
  { ref: "L1", title: "甲", document_id: "d1" },
  { ref: "L2", title: "乙", document_id: "d1" },
];

test("linkifyCitationRefs converts known refs to citation links", () => {
  const out = linkifyCitationRefs("見 [L1] 與 **重點**，另有 [L9]", cites);
  assert.match(out, /\[L1\]\(citation:L1\)/);
  assert.match(out, /\*\*重點\*\*/);
  assert.match(out, /\[L9\]/);
  assert.doesNotMatch(out, /citation:L9/);
});

test("linkifyCitationRefs links web refs separately from local ones", () => {
  const mixed: Citation[] = [
    { ref: "L1", title: "通告", document_id: "d1", backend: "local" },
    { ref: "W1", title: "網頁", source_url: "https://www.edb.gov.hk/a", backend: "web" },
  ];
  const out = linkifyCitationRefs("本機 [L1]，網上 [W1]", mixed);
  assert.match(out, /\[L1\]\(citation:L1\)/);
  assert.match(out, /\[W1\]\(citation:W1\)/);
});

test("linkifyCitationRefs leaves content unchanged without citations", () => {
  assert.equal(linkifyCitationRefs("見 [L1]", undefined), "見 [L1]");
  assert.equal(linkifyCitationRefs("見 [L1]", []), "見 [L1]");
});

test("citationRefFromHref and url transform", () => {
  assert.equal(citationRefFromHref("citation:L1"), "L1");
  assert.equal(citationRefFromHref("https://example.com"), null);
  assert.equal(chatUrlTransform("citation:L2"), "citation:L2");
  assert.equal(chatUrlTransform("https://a.com"), "https://a.com");
  assert.equal(chatUrlTransform("javascript:alert(1)"), "");
  assert.equal(isSafeExternalHref("https://a.com"), true);
  assert.equal(isSafeExternalHref("mailto:a@b.com"), true);
  assert.equal(isSafeExternalHref("javascript:alert(1)"), false);
});
