import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, apiBaseUrl, safeApiPath } from "@/lib/server";

// Forwards browser requests to the FastAPI back end, adding the bearer token
// from the httpOnly session cookie. The browser never holds the token, and
// only /api/v1 paths made of plain segments are forwarded.

type Context = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, context: Context): Promise<Response> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Your session has ended. Sign in again." }, { status: 401 });
  }

  const { path } = await context.params;
  const safe = safeApiPath(path);
  if (!safe) {
    return NextResponse.json({ detail: "Unknown API path." }, { status: 404 });
  }

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  let body: string | undefined;
  if (request.method !== "GET") {
    // Only JSON bodies: a cross-site form post can't set this content type,
    // which backs up the SameSite=Strict cookie against CSRF.
    const type = request.headers.get("content-type") ?? "";
    const text = await request.text();
    if (text) {
      if (!type.startsWith("application/json")) {
        return NextResponse.json({ detail: "Requests must be JSON." }, { status: 415 });
      }
      headers["Content-Type"] = "application/json";
      body = text;
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/api/v1/${safe}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: "The portfolio API isn't reachable. Check that it's running." },
      { status: 502 },
    );
  }

  const response = new NextResponse(upstream.status === 204 ? null : await upstream.text(), {
    status: upstream.status,
  });
  const type = upstream.headers.get("content-type");
  if (type) response.headers.set("Content-Type", type);
  response.headers.set("Cache-Control", "no-store");
  if (upstream.status === 401) {
    response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  }
  return response;
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
