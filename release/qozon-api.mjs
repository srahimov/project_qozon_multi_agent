/** Public chat client: no credentials, no automatic retries, no conversation uploads. */
export async function askQuestion(apiBaseUrl, question, { signal } = {}) {
  if (typeof question !== "string" || !question.trim() || [...question].length > 200) {
    throw new Error("Enter a question of 1–200 characters.");
  }
  const response = await fetch(`${apiBaseUrl.replace(/\/+$/, "")}/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "omit",
    body: JSON.stringify({ question }),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(60_000)])
      : AbortSignal.timeout(60_000),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.detail?.message ?? "Question answering is unavailable.");
    error.status = response.status;
    error.code = body?.detail?.code ?? "request_failed";
    const retryAfter = Number(response.headers.get("Retry-After"));
    error.retryAfter = Number.isInteger(retryAfter) && retryAfter > 0 ? retryAfter : null;
    throw error;
  }
  if (typeof body?.answer !== "string" || !body.answer.trim()
      || (body.sources !== undefined && !Array.isArray(body.sources))) {
    throw new Error("The API returned an invalid response.");
  }
  return { answer: body.answer, sources: body.sources ?? [] };
}
