import { DurableObject } from "cloudflare:workers";

interface Env {
  BACKEND: DurableObjectNamespace<QozonBackend>;
  ALLOWED_ORIGIN: string;
  QUESTIONS_PER_MINUTE: string;
  QUESTIONS_PER_DAY: string;
  INACTIVITY_SECONDS: string;
  OPENAI_API_KEY: string;
  LANGSMITH_API_KEY: string;
  SUPABASE_URL: string;
  SUPABASE_PUBLISHABLE_KEY: string;
  QOZON_QUESTION_LIMIT_KEY: string;
}

const SERVICE = "public-api-v1"; // Keep stable across deploys, hostnames and rollbacks.
const ADMISSION = "X-Qozon-Admission";
const CLIENT = "X-Qozon-Client";
const QUESTION_BYTES = 4096;
const EDGE_DEADLINE = 55_000;
const STARTUP_DEADLINE = 15_000;
const UUID = "[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}";
const DOCUMENT_ROUTE = new RegExp(`^/documents/${UUID}(?:/citations/[a-f0-9]{64}/(?:image|structured|text))?$`);

function deadlineFor(parent: AbortSignal, milliseconds: number) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("Request timed out", "TimeoutError")), milliseconds);
  return {signal: AbortSignal.any([parent, controller.signal]), clear: () => clearTimeout(timer)};
}

async function withAbort<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) {
    void work.catch(() => {});
    throw signal.reason;
  }
  let abort!: () => void;
  const interrupted = new Promise<never>((_, reject) => {
    abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, {once: true});
  });
  try { return await Promise.race([work, interrupted]); }
  finally { signal.removeEventListener("abort", abort); }
}

function failure(status: number, code: string, retryAfter?: number): Response {
  const headers = new Headers({"Content-Type": "application/json", "Cache-Control": "no-store"});
  if (retryAfter !== undefined) headers.set("Retry-After", String(retryAfter));
  return new Response(JSON.stringify({detail: {code, message:
    status === 429 ? "Question limit reached. Please try again later." :
    status === 422 ? "Question request is invalid." : "The request could not be completed."}}), {status, headers});
}

function publicMethod(path: string): string | undefined {
  if (path === "/questions") return "POST";
  if (path === "/health" || path === "/documents" || DOCUMENT_ROUTE.test(path)) return "GET";
}

function browserResponse(response: Response, request: Request, env: Env): Response {
  const headers = new Headers(response.headers);
  // Do not preserve backend CORS or credentials; the edge owns browser access.
  for (const name of [...headers.keys()]) if (name.toLowerCase().startsWith("access-control-")) headers.delete(name);
  headers.set("Cache-Control", "no-store");
  headers.set("Vary", "Origin");
  headers.delete("Set-Cookie");
  headers.delete(ADMISSION);
  headers.delete(CLIENT);
  if (request.headers.get("Origin") === env.ALLOWED_ORIGIN) {
    headers.set("Access-Control-Allow-Origin", env.ALLOWED_ORIGIN);
    headers.set("Access-Control-Expose-Headers", "Retry-After");
  }
  return new Response(response.body, {status: response.status, headers});
}

async function questionBody(request: Request): Promise<string | undefined> {
  if (request.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "application/json") return;
  const reader = request.body?.getReader();
  if (!reader) return;
  const chunks: Uint8Array[] = [];
  let length = 0;
  const deadline = deadlineFor(request.signal, 10_000);
  const signal = deadline.signal;
  try {
    while (true) {
      const {done, value} = await withAbort(reader.read(), signal);
      if (done) break;
      length += value.length;
      if (length > QUESTION_BYTES) return;
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    const body = JSON.parse(new TextDecoder("utf-8", {fatal: true, ignoreBOM: false}).decode(bytes));
    if (!body || Array.isArray(body) || typeof body !== "object" || Object.keys(body).length !== 1
        || typeof body.question !== "string" || !body.question.trim()
        || [...body.question].length > 200) return;
    return JSON.stringify({question: body.question});
  } catch { return; }
  finally { deadline.clear(); void reader.cancel().catch(() => {}); }
}

function positiveInteger(value: string, maximum: number): number {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1 || number > maximum) throw new Error("configuration_unavailable");
  return number;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    let response: Response;
    const deadline = deadlineFor(request.signal, EDGE_DEADLINE);
    const signal = deadline.signal;
    try {
      const url = new URL(request.url);
      const method = publicMethod(url.pathname);
      const origin = request.headers.get("Origin");
      if (!method) response = failure(404, "not_found");
      else if (origin && origin !== env.ALLOWED_ORIGIN) response = failure(403, "origin_not_allowed");
      else if (request.method === "OPTIONS") {
        const requestedHeaders = (request.headers.get("Access-Control-Request-Headers") || "")
          .split(",").map(h => h.trim().toLowerCase()).filter(Boolean);
        if (origin !== env.ALLOWED_ORIGIN || request.headers.get("Access-Control-Request-Method") !== method
            || requestedHeaders.some(h => h !== "content-type")) response = failure(403, "preflight_not_allowed");
        else response = new Response(null, {status: 204, headers: {
          "Access-Control-Allow-Methods": method, "Access-Control-Allow-Headers": "Content-Type",
        }});
      } else if (request.method !== method) response = failure(405, "method_not_allowed");
      else {
        // Only these headers cross the internal binding. Visitor admission/XFF/auth headers do not.
        signal.throwIfAborted();
        const headers = new Headers({Accept: "application/json"});
        let body: string | undefined;
        if (method === "POST") {
          body = await questionBody(request);
          if (body === undefined) return browserResponse(failure(422, "invalid_request"), request, env);
          const client = request.headers.get("CF-Connecting-IP");
          if (!client) return browserResponse(failure(503, "client_identity_unavailable"), request, env);
          headers.set(CLIENT, client);
          headers.set("Content-Type", "application/json");
        }
        response = await withAbort(env.BACKEND.getByName(SERVICE).fetch(new Request(url, {
          method, headers, body, signal, redirect: "manual",
        })), signal);
      }
    } catch { response = failure(signal.aborted ? 504 : 503, signal.aborted ? "question_timeout" : "backend_unavailable"); }
    finally { deadline.clear(); }
    const result = browserResponse(response, request, env);
    // browserResponse removes all upstream CORS; explicitly add the validated preflight policy.
    if (response.status === 204 && request.method === "OPTIONS") {
      result.headers.set("Access-Control-Allow-Methods", publicMethod(new URL(request.url).pathname)!);
      result.headers.set("Access-Control-Allow-Headers", "Content-Type");
    }
    return result;
  },
};

export class QozonBackend extends DurableObject<Env> {
  private starting?: Promise<void>;
  private ready = false;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS requests (scope TEXT, client TEXT, expires INTEGER, " +
      "total INTEGER NOT NULL, PRIMARY KEY(scope, client))");
    if (ctx.container?.running) {
      void ctx.blockConcurrencyWhile(() =>
        ctx.container!.setInactivityTimeout(positiveInteger(env.INACTIVITY_SECONDS, 3600) * 1000));
    }
  }

  private async reserve(client: string): Promise<Response | undefined> {
    const key = this.env.QOZON_QUESTION_LIMIT_KEY;
    if (!key || key.length < 32 || !client) throw new Error("admission_unavailable");
    const minuteLimit = positiveInteger(this.env.QUESTIONS_PER_MINUTE, 100);
    const dailyLimit = positiveInteger(this.env.QUESTIONS_PER_DAY, 10_000);
    const now = Math.floor(Date.now() / 1000);
    const hmacKey = await crypto.subtle.importKey("raw", new TextEncoder().encode(key),
      {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
    const digest = await crypto.subtle.sign("HMAC", hmacKey, new TextEncoder().encode(`${Math.floor(now / 86400)}:${client}`));
    const identity = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
    const counters = [
      {scope: `minute:${Math.floor(now / 60)}`, client: identity, expires: (Math.floor(now / 60) + 1) * 60,
        limit: minuteLimit, code: "question_rate_limited"},
      {scope: `day:${Math.floor(now / 86400)}`, client: "all", expires: (Math.floor(now / 86400) + 1) * 86400,
        limit: dailyLimit, code: "daily_question_limit_reached"},
    ];
    // Commit admission before awaiting startup/model work. Failures do not refund a slot.
    return this.ctx.storage.transactionSync(() => {
      const sql = this.ctx.storage.sql;
      sql.exec("DELETE FROM requests WHERE expires <= ?", now);
      for (const counter of counters) {
        const rows = sql.exec<{total: number}>("SELECT total FROM requests WHERE scope=? AND client=?",
          counter.scope, counter.client).toArray();
        if (rows[0]?.total >= counter.limit) return failure(429, counter.code, Math.max(1, counter.expires - now));
      }
      for (const counter of counters) sql.exec("INSERT INTO requests VALUES (?, ?, ?, 1) " +
        "ON CONFLICT(scope, client) DO UPDATE SET total=total+1", counter.scope, counter.client, counter.expires);
    });
  }

  private async ensureReady(): Promise<void> {
    const container = this.ctx.container;
    if (!container) throw new Error("container_unavailable");
    if (!container.running) this.ready = false;
    if (this.ready) return;
    this.starting ??= this.startAndWait().finally(() => { this.starting = undefined; });
    await this.starting;
  }

  private async startAndWait(): Promise<void> {
    const container = this.ctx.container!;
    const env = this.env;
    if (!env.OPENAI_API_KEY || !env.SUPABASE_URL || !env.SUPABASE_PUBLISHABLE_KEY
        || !env.QOZON_QUESTION_LIMIT_KEY || env.QOZON_QUESTION_LIMIT_KEY.length < 32) throw new Error("configuration_unavailable");
    if (!container.running) container.start({enableInternet: true, env: {
      OPENAI_API_KEY: env.OPENAI_API_KEY,
      SUPABASE_URL: env.SUPABASE_URL,
      SUPABASE_PUBLISHABLE_KEY: env.SUPABASE_PUBLISHABLE_KEY,
      SUPABASE_ASSETS_BUCKET: "canon-of-medicine-chunks",
      QOZON_RAG_BACKEND: "supabase", QOZON_RAG_ENABLED: "true", QOZON_OUTPUT_MAX_TOKENS: "512",
      QOZON_QUESTION_LIMITS_ENABLED: "true", QOZON_QUESTION_LIMITS_BACKEND: "cloudflare",
      QOZON_QUESTION_LIMIT_KEY: env.QOZON_QUESTION_LIMIT_KEY,
      LANGSMITH_TRACING: "true", QOZON_LANGSMITH_TRACE_CONTENT: "false",
      LANGSMITH_API_KEY: env.LANGSMITH_API_KEY,
      LANGSMITH_PROJECT: "qozon-production",
      QOZON_CORS_ORIGINS: "[]",
    }});
    await container.setInactivityTimeout(positiveInteger(env.INACTIVITY_SECONDS, 3600) * 1000);
    const port = container.getTcpPort(8000);
    const until = Date.now() + STARTUP_DEADLINE;
    do {
      const deadline = deadlineFor(new AbortController().signal, 1000);
      try {
        const response = await withAbort(port.fetch("http://container/health", {signal: deadline.signal}), deadline.signal);
        await response.body?.cancel();
        if (response.ok) { this.ready = true; return; }
      } catch { /* Retry liveness only; never retry a question. */ }
      finally { deadline.clear(); }
      await scheduler.wait(200);
    } while (Date.now() < until);
    throw new Error("container_not_ready");
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const method = publicMethod(url.pathname);
    if (!method) return failure(404, "not_found");
    if (request.method !== method) return failure(405, "method_not_allowed");
    let body: string | undefined;
    const headers = new Headers({Accept: "application/json"});
    try {
      if (method === "POST") {
        body = await questionBody(request);
        if (body === undefined) return failure(422, "invalid_request");
        const limited = await this.reserve(request.headers.get(CLIENT) || "");
        if (limited) return limited;
        headers.set("Content-Type", "application/json");
        headers.set(ADMISSION, this.env.QOZON_QUESTION_LIMIT_KEY);
      }
    } catch { return failure(503, "question_limits_unavailable"); }
    const deadline = deadlineFor(request.signal, EDGE_DEADLINE);
    const signal = deadline.signal;
    try {
      await withAbort(this.ensureReady(), signal);
      signal.throwIfAborted();
      url.protocol = "http:";
      url.host = "container";
      const response = await withAbort(this.ctx.container!.getTcpPort(8000).fetch(new Request(url, {
        method, headers, body, signal, redirect: "manual",
      })), signal);
      // Keep the answer buffered under the edge deadline; do not stream unchecked partial output.
      const bytes = await withAbort(response.arrayBuffer(), signal);
      signal.throwIfAborted();
      return new Response(bytes, {status: response.status, headers: response.headers});
    } catch {
      this.ready = false;
      return failure(signal.aborted ? 504 : 503, signal.aborted ? "question_timeout" : "backend_unavailable");
    }
    finally { deadline.clear(); }
  }
}
