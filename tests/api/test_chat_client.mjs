import assert from "node:assert/strict";
import { test } from "node:test";
import { askQuestion } from "../../release/qozon-api.mjs";

test("chat handoff sends one public question and preserves approved sources", async (t) => {
  const calls = [];
  const sources = [{ citation_id: "C1", physical_pages: [2], url: "https://assets.example/reviewed.png" }];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return Response.json({ answer: "A checked answer.", sources });
  });
  assert.deepEqual(await askQuestion("https://api.example/", "A question?"), { answer: "A checked answer.", sources });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.example/questions");
  assert.equal(calls[0].options.credentials, "omit");
  assert.deepEqual(JSON.parse(calls[0].options.body), { question: "A question?" });
  assert.deepEqual(calls[0].options.headers, { "Content-Type": "application/json" });
  assert.ok(calls[0].options.signal instanceof AbortSignal);
});

test("Unicode character limit matches Python code points; invalid input sends nothing", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => { calls++; return Response.json({ answer: "Checked." }); });
  assert.deepEqual(await askQuestion("https://api.example", "😀".repeat(200)), { answer: "Checked.", sources: [] });
  for (const question of ["😀".repeat(201), "  ", 123]) {
    await assert.rejects(askQuestion("https://api.example", question), /1–200/);
  }
  assert.equal(calls, 1);
});

test("429 exposes a safe retry delay and never automatically retries", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return Response.json({ detail: { code: "question_rate_limited", message: "Try later." } },
                         { status: 429, headers: { "Retry-After": "25" } });
  });
  await assert.rejects(askQuestion("https://api.example", "A question?"), error => {
    assert.equal(error.status, 429);
    assert.equal(error.code, "question_rate_limited");
    assert.equal(error.retryAfter, 25);
    return true;
  });
  assert.equal(calls, 1);
});

test("non-JSON provider/edge errors remain generic and are not retried", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return new Response("synthetic-private-upstream-content", { status: 503 });
  });
  await assert.rejects(askQuestion("https://api.example", "A question?"), error => {
    assert.equal(error.status, 503);
    assert.equal(error.message, "Question answering is unavailable.");
    assert.equal(error.retryAfter, null);
    return true;
  });
  assert.equal(calls, 1);
});

test("invalid successful payload is not displayed as an answer", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ answer: "", sources: "invalid" }));
  await assert.rejects(askQuestion("https://api.example", "A question?"), /invalid response/);
});

test("caller cancellation is passed to fetch and is not retried", async (t) => {
  const controller = new AbortController();
  controller.abort();
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    calls++;
    assert.equal(options.signal.aborted, true);
    throw options.signal.reason;
  });
  await assert.rejects(askQuestion("https://api.example", "A question?", { signal: controller.signal }),
                       { name: "AbortError" });
  assert.equal(calls, 1);
});
