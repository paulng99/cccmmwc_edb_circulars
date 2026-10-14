import assert from "node:assert/strict";
import test from "node:test";
import { improveSystemPromptErrorMessage } from "./improve-system-prompt-error.ts";

const FALLBACK = "Could not improve the system prompt";

test("empty error uses fallback", () => {
  assert.equal(improveSystemPromptErrorMessage(new Error(""), FALLBACK), FALLBACK);
  assert.equal(improveSystemPromptErrorMessage(null, FALLBACK), FALLBACK);
});

test("known API detail codes use fallback", () => {
  assert.equal(
    improveSystemPromptErrorMessage(new Error(JSON.stringify({ detail: "prompt_empty" })), FALLBACK),
    FALLBACK,
  );
  assert.equal(
    improveSystemPromptErrorMessage(new Error(JSON.stringify({ detail: "improve_failed" })), FALLBACK),
    FALLBACK,
  );
});

test("readable detail string is surfaced", () => {
  assert.equal(
    improveSystemPromptErrorMessage(
      new Error(JSON.stringify({ detail: "OpenRouter API key is missing" })),
      FALLBACK,
    ),
    "OpenRouter API key is missing",
  );
});

test("non-JSON body uses fallback", () => {
  assert.equal(improveSystemPromptErrorMessage(new Error("network down"), FALLBACK), FALLBACK);
});
