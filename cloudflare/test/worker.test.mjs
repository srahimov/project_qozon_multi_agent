// Real SQLite transactions with a scripted container: no cloud account or model calls.
import assert from "node:assert/strict";
import {registerHooks} from "node:module";
import {DatabaseSync} from "node:sqlite";
import {mkdtempSync, rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";

registerHooks({
  resolve(specifier, context, next) {
    return specifier === "cloudflare:workers" ? {url: "qozon:workers", shortCircuit: true} : next(specifier, context);
  },
  load(url, context, next) {
    return url === "qozon:workers" ? {format: "module", shortCircuit: true,
      source: "export class DurableObject { constructor(ctx, env) { this.ctx = ctx; this.env = env; } }"} : next(url, context);
  },
});
globalThis.scheduler = {wait: ms => new Promise(resolve => setTimeout(resolve, ms))};
const {default: worker, QozonBackend} = await import("../src/index.ts");
const KEY = "synthetic-private-counter-key-at-least-32-characters";
const SITE = "https://srahimov.site";
const DOC = "2d6b499b-568c-443d-a167-c43767e23a02";

function fixture({path = ":memory:", limit = 5, daily = 100, handler, health, sqlFailure = false} = {}) {
  const db = new DatabaseSync(path);
  const seen = [];
  const starts = [];
  const sql = {exec(query, ...values) {
    if (sqlFailure && query.startsWith("INSERT")) throw new Error("synthetic-private-database-error");
    const statement = db.prepare(query);
    const rows = statement.columns().length ? statement.all(...values) : (statement.run(...values), []);
    return {toArray: () => rows};
  }};
  const ctx = {blockConcurrencyWhile: callback => callback(), storage: {sql, transactionSync(callback) {
    db.exec("BEGIN IMMEDIATE");
    try { const result = callback(); db.exec("COMMIT"); return result; }
    catch (error) { db.exec("ROLLBACK"); throw error; }
  }}, container: {
    running: false,
    start(options) { this.running = true; starts.push(options); },
    async setInactivityTimeout(ms) { this.idle = ms; },
    getTcpPort(port) {
      assert.equal(port, 8000);
      return {async fetch(input, options) {
        const request = input instanceof Request ? input : new Request(input, options);
        if (new URL(request.url).pathname === "/health") return health ? health() : new Response('{"status":"ok"}');
        seen.push({method: request.method, url: request.url, headers: Object.fromEntries(request.headers),
          redirect: request.redirect, body: await request.clone().text()});
        return handler ? handler(request) : new Response('{"answer":"A checked answer.","sources":[]}', {
          headers: {"Content-Type": "application/json"},
        });
      }};
    },
  }};
  const env = {ALLOWED_ORIGIN: SITE, QUESTIONS_PER_MINUTE: String(limit), QUESTIONS_PER_DAY: String(daily),
    INACTIVITY_SECONDS: "300", OPENAI_API_KEY: "synthetic-offline-key", SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_PUBLISHABLE_KEY: "synthetic-publishable", QOZON_QUESTION_LIMIT_KEY: KEY};
  let backend = new QozonBackend(ctx, env);
  const names = [];
  env.BACKEND = {getByName(name) { names.push(name); return {async fetch(request) {
    const response = await backend.fetch(request);
    // Service-binding fetch follows redirects unless the caller requests manual handling.
    if ([301, 302, 303, 307, 308].includes(response.status) && request.redirect === "follow") {
      return backend.fetch(new Request(response.headers.get("Location")));
    }
    return response;
  }}; }};
  return {db, ctx, env, seen, starts, names,
    restart() { backend = new QozonBackend(ctx, env); },
    request(path = "/questions", {method = "POST", headers = {}, body = {question: "Find repair services?"}, signal} = {}) {
      return worker.fetch(new Request(`https://api.example${path}`, {method, signal,
        headers: {Origin: SITE, "CF-Connecting-IP": "192.0.2.1", ...(method === "POST" ? {"Content-Type": "application/json"} : {}), ...headers},
        ...(method === "POST" ? {body: typeof body === "string" ? body : JSON.stringify(body)} : {}),
      }), env);
    },
  };
}

test("all hostnames share one identity; visitor secrets/forwarding headers cannot cross", async t => {
  const f = fixture(); t.after(() => f.db.close());
  const response = await f.request("/questions", {headers: {
    "X-Qozon-Admission": "forged", "X-Qozon-Client": "forged-client", "X-Forwarded-For": "192.0.2.88",
    Authorization: "visitor-token", Cookie: "visitor-cookie",
  }});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(f.names, ["public-api-v1"]);
  assert.equal(f.seen[0].headers["x-qozon-admission"], KEY);
  for (const header of ["x-qozon-client", "x-forwarded-for", "authorization", "cookie"]) assert.equal(f.seen[0].headers[header], undefined);
  assert.equal(f.seen[0].body, '{"question":"Find repair services?"}');
  const env = f.starts[0].env;
  assert.equal(env.QOZON_QUESTION_LIMITS_BACKEND, "cloudflare");
  for (const key of ["SUPABASE_SECRET_KEY", "SUPABASE_STORAGE_BUCKET", "LANGSMITH_API_KEY"]) assert.equal(env[key], undefined);
  const stored = JSON.stringify(f.db.prepare("SELECT * FROM requests").all());
  for (const privateValue of ["192.0.2.1", KEY, "Find repair services?"]) assert.equal(stored.includes(privateValue), false);
});

test("concurrent questions reserve exactly the shared allowance before forwarding", async t => {
  const f = fixture({limit: 100, daily: 3}); t.after(() => f.db.close());
  const responses = await Promise.all(Array.from({length: 12}, (_, i) => f.request("/questions", {
    headers: {"CF-Connecting-IP": `192.0.2.${i + 1}`},
  })));
  assert.equal(responses.filter(r => r.status === 200).length, 3);
  assert.equal(responses.filter(r => r.status === 429).length, 9);
  assert.equal(f.seen.length, 3);
  assert.equal(f.starts.length, 1);
  const blocked = responses.find(r => r.status === 429);
  assert.equal(blocked.headers.get("Access-Control-Expose-Headers"), "Retry-After");
  assert.ok(Number(blocked.headers.get("Retry-After")) > 0);
});

test("one slow question does not hold the admission transaction or block another", async t => {
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  const f = fixture({handler: async request => {
    if ((await request.json()).question === "First?") await waiting;
    return new Response('{"answer":"A checked answer."}');
  }}); t.after(() => f.db.close());
  const first = f.request("/questions", {body: {question: "First?"}});
  const second = await f.request("/questions", {body: {question: "Second?"}});
  assert.equal(second.status, 200);
  release();
  assert.equal((await first).status, 200);
});

test("startup waits for readiness and concurrent questions share that wait", async t => {
  let checks = 0;
  const f = fixture({health: () => new Response("", {status: ++checks === 1 ? 503 : 200})});
  t.after(() => f.db.close());
  const questions = [f.request(), f.request()];
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(f.seen.length, 0);
  assert.deepEqual((await Promise.all(questions)).map(r => r.status), [200, 200]);
  assert.equal(f.starts.length, 1);
  assert.equal(checks, 2);
});

test("failed startup retains its slot and a later request can recover", async t => {
  let now = 86400_000;
  let healthy = false;
  const originalNow = Date.now;
  Date.now = () => now;
  t.after(() => { Date.now = originalNow; });
  const f = fixture({health: () => {
    if (!healthy) { now += 16000; throw new Error("synthetic-private-startup-error"); }
    return new Response("");
  }});
  t.after(() => f.db.close());
  assert.equal((await f.request()).status, 503);
  assert.equal(f.seen.length, 0);
  healthy = true;
  assert.equal((await f.request()).status, 200);
  assert.equal(f.db.prepare("SELECT total FROM requests WHERE client='all'").get().total, 2);
});

test("missing deployment secrets fail closed without sending a question", async t => {
  const f = fixture(); t.after(() => f.db.close());
  f.env.OPENAI_API_KEY = "";
  assert.equal((await f.request()).status, 503);
  assert.equal(f.starts.length, 0);
  assert.equal(f.seen.length, 0);
});

test("minute/day resets and SQLite reopen preserve the quota through sleep/restart", async t => {
  const directory = mkdtempSync(join(tmpdir(), "qozon-counter-"));
  t.after(() => rmSync(directory, {recursive: true, force: true}));
  const originalNow = Date.now;
  let seconds = 86400;
  Date.now = () => seconds * 1000;
  t.after(() => { Date.now = originalNow; });
  const path = join(directory, "counters.sqlite");
  let f = fixture({path, limit: 1, daily: 2});
  assert.equal((await f.request()).status, 200);
  f.ctx.container.running = false;
  f.restart();
  assert.equal((await f.request()).status, 429);
  assert.equal(f.starts.length, 1);
  seconds += 60;
  assert.equal((await f.request()).status, 200);
  f.db.close();
  f = fixture({path, limit: 1, daily: 2}); t.after(() => f.db.close());
  const blocked = await f.request("/questions", {headers: {"CF-Connecting-IP": "192.0.2.2"}});
  assert.equal((await blocked.json()).detail.code, "daily_question_limit_reached");
  assert.equal(f.starts.length, 0);
  seconds = 172800;
  assert.equal((await f.request()).status, 200);
});

test("object restart restores inactivity policy for an already running container", async t => {
  const f = fixture(); t.after(() => f.db.close());
  f.ctx.container.running = true;
  f.restart();
  assert.equal(f.ctx.container.idle, 300_000);
});

test("provider failures keep their slot and never automatically repeat a POST", async t => {
  const f = fixture({daily: 1, handler() { throw new Error("synthetic-private-provider-error"); }});
  t.after(() => f.db.close());
  const failed = await f.request();
  assert.equal(failed.status, 503);
  assert.equal((await failed.text()).includes("synthetic-private"), false);
  assert.equal((await f.request()).status, 429);
  assert.equal(f.seen.length, 1);
});

test("SQLite errors roll back and prevent startup/model forwarding", async t => {
  const f = fixture({sqlFailure: true}); t.after(() => f.db.close());
  const response = await f.request();
  assert.equal(response.status, 503);
  assert.equal((await response.json()).detail.code, "question_limits_unavailable");
  assert.equal(f.starts.length, 0);
  assert.equal(f.seen.length, 0);
  assert.equal(f.db.prepare("SELECT count(*) AS total FROM requests").get().total, 0);
});

for (const body of [{question: ""}, {question: "   "}, {question: 4}, {question: "x", history: []},
                    {question: "x".repeat(201)}, "{bad-json", " ".repeat(4097)]) {
  test(`invalid bounded question does not reserve or start: ${JSON.stringify(body).slice(0, 40)}`, async t => {
    const f = fixture(); t.after(() => f.db.close());
    assert.equal((await f.request("/questions", {body})).status, 422);
    assert.equal(f.starts.length, 0);
    assert.equal(f.db.prepare("SELECT count(*) AS total FROM requests").get().total, 0);
  });
}

test("Unicode length matches Python codepoints and counts original spaces", async t => {
  const f = fixture(); t.after(() => f.db.close());
  assert.equal((await f.request("/questions", {body: {question: "😀".repeat(200)}})).status, 200);
  assert.equal((await f.request("/questions", {body: {question: "😀".repeat(200) + " "}})).status, 422);
});

test("preflight is quota-free and allows only the exact origin/method/header", async t => {
  const f = fixture(); t.after(() => f.db.close());
  const headers = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"};
  const good = await f.request("/questions", {method: "OPTIONS", headers});
  assert.equal(good.status, 204);
  assert.equal(good.headers.get("Access-Control-Allow-Methods"), "POST");
  assert.equal(good.headers.get("Access-Control-Allow-Origin"), SITE);
  for (const changed of [{Origin: "https://evil.example"}, {"Access-Control-Request-Method": "DELETE"},
                         {"Access-Control-Request-Headers": "X-Qozon-Admission"}]) {
    assert.equal((await f.request("/questions", {method: "OPTIONS", headers: {...headers, ...changed}})).status, 403);
  }
  assert.equal(f.names.length, 0);
});

test("public non-browser questions work; missing edge client identity fails closed", async t => {
  const f = fixture(); t.after(() => f.db.close());
  assert.equal((await f.request("/questions", {headers: {Origin: ""}})).status, 200);
  assert.equal((await f.request("/questions", {headers: {"CF-Connecting-IP": ""}})).status, 503);
  assert.equal(f.seen.length, 1);
});

test("public reads do not consume questions and approved citation redirects stay manual", async t => {
  const asset = "https://example.supabase.co/storage/v1/object/public/approved/asset.png";
  const f = fixture({handler: () => new Response(null, {status: 307, headers: {Location: asset}})});
  t.after(() => f.db.close());
  for (const path of ["/health", "/documents", `/documents/${DOC}`, `/documents/${DOC}/citations/${"a".repeat(64)}/image`]) {
    const response = await f.request(path, {method: "GET"});
    if (path.includes("/citations/")) assert.equal(response.headers.get("Location"), asset);
  }
  assert.equal(f.db.prepare("SELECT count(*) AS total FROM requests").get().total, 0);
  assert.equal(f.seen.at(-1).redirect, "manual");
  assert.equal((await f.request(`/documents/${DOC}/source`, {method: "GET"})).status, 404);
  assert.equal((await f.request("/docs", {method: "GET"})).status, 404);
  assert.equal((await f.request("/questions", {method: "GET"})).status, 405);
});

test("deadline returns a safe error, keeps quota and the next request recovers", async t => {
  const originalTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (callback, ms, ...args) => originalTimeout(callback, ms === 55_000 ? 40 : ms, ...args);
  t.after(() => { globalThis.setTimeout = originalTimeout; });
  let count = 0;
  const f = fixture({handler: request => ++count === 1 ? new Promise((_, reject) => {
    request.signal.addEventListener("abort", () => reject(request.signal.reason), {once: true});
  }) : new Response('{"answer":"A checked answer."}')});
  t.after(() => f.db.close());
  const keepAlive = setTimeout(() => {}, 1000); t.after(() => clearTimeout(keepAlive));
  assert.equal((await f.request()).status, 504);
  assert.equal((await f.request()).status, 200);
  assert.equal(f.db.prepare("SELECT total FROM requests WHERE client='all'").get().total, 2);
  assert.equal(count, 2);
});
