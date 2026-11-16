import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, SESSION_MAX_AGE, apiBaseUrl } from "@/lib/server";

// Sign in: check the token against the API, then keep it in an httpOnly cookie
// so browser JavaScript can never read it. A stand-in until a real identity
// provider with MFA replaces the static API token.
export async function POST(request: NextRequest) {
  let token = "";
  try {
    const body = (await request.json()) as { token?: unknown };
    token = typeof body.token === "string" ? body.token.trim() : "";
  } catch {
    return NextResponse.json({ detail: "Send the token as JSON." }, { status: 400 });
  }
  if (!token) {
    return NextResponse.json({ detail: "Enter your API token." }, { status: 400 });
  }

  let check: Response;
  try {
    check = await fetch(`${apiBaseUrl()}/api/v1/portfolios`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: "The portfolio API isn't reachable. Check that it's running." },
      { status: 502 },
    );
  }
  if (check.status === 401) {
    return NextResponse.json({ detail: "That token wasn't accepted." }, { status: 401 });
  }
  if (!check.ok) {
    return NextResponse.json(
      { detail: `The portfolio API returned an error (${check.status}).` },
      { status: 502 },
    );
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return response;
}

// Sign out.
export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return response;
}
