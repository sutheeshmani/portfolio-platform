import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "pp_session";
const PUBLIC_PATHS = ["/login", "/api/session"];

// Every page except sign-in needs a session; the API proxy answers 401 itself.
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }
  if (pathname.startsWith("/api/")) return NextResponse.next();
  if (!request.cookies.get(SESSION_COOKIE)?.value) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
