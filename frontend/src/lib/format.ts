// Display formatting for decimal strings. Rounding is done on the digits
// themselves (BigInt), so values never pass through binary floating point.

const PLAIN = /^(-)?(\d+)(?:\.(\d+))?$/;
const MINUS = "−";

function toPlain(value: string): string | null {
  const v = value.trim();
  if (PLAIN.test(v)) return v;
  // Python's Decimal can serialise as "1E+3" or "0E-8".
  const m = /^(-)?(\d+)(?:\.(\d+))?[eE]([+-]?\d+)$/.exec(v);
  if (!m) return null;
  const sign = m[1] ?? "";
  const digits = (m[2] + (m[3] ?? "")).replace(/^0+(?=\d)/, "");
  const point = m[2].length + Number(m[4]);
  if (point <= 0) return `${sign}0.${"0".repeat(-point)}${digits}`;
  if (point >= digits.length) return sign + digits + "0".repeat(point - digits.length);
  return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`;
}

/** Round half-up to `dp` places and group thousands. Returns null for bad input. */
export function decimal(value: string | null | undefined, dp = 2): string | null {
  if (value == null || value === "") return null;
  const plain = toPlain(value);
  if (plain == null) return null;
  const m = PLAIN.exec(plain)!;
  const negative = Boolean(m[1]);
  const frac = (m[3] ?? "").padEnd(dp + 1, "0");
  let scaled = BigInt(m[2] + frac.slice(0, dp));
  if (Number(frac[dp]) >= 5) scaled += 1n;
  const digits = scaled.toString().padStart(dp + 1, "0");
  const whole = digits.slice(0, digits.length - dp).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const text = dp > 0 ? `${whole}.${digits.slice(digits.length - dp)}` : whole;
  return negative && scaled !== 0n ? MINUS + text : text;
}

/** Sign of a decimal string: -1, 0 or 1. */
export function sign(value: string | null | undefined): -1 | 0 | 1 {
  const plain = value == null ? null : toPlain(value);
  if (plain == null || /^-?0*(\.0*)?$/.test(plain)) return 0;
  return plain.startsWith("-") ? -1 : 1;
}

const PREFIX: Record<string, string> = { AUD: "A$", USD: "US$" };

export function money(value: string | null | undefined, currency = "AUD", dp = 2): string {
  const text = decimal(value, dp);
  if (text == null) return "—";
  const prefix = PREFIX[currency] ?? `${currency} `;
  return text.startsWith(MINUS) ? `${MINUS}${prefix}${text.slice(1)}` : `${prefix}${text}`;
}

/** Money with an explicit + for gains, for P&L figures. */
export function signedMoney(value: string | null | undefined, currency = "AUD"): string {
  const text = money(value, currency);
  return sign(value) > 0 ? `+${text}` : text;
}

/** Quantity: up to 8 places, trailing zeros trimmed. */
export function quantity(value: string | null | undefined): string {
  const text = decimal(value, 8);
  if (text == null) return "—";
  return text.includes(".") ? text.replace(/\.?0+$/, "") : text;
}

/** A 0..1 weight as a percentage. */
export function percent(value: string | null | undefined, dp = 1): string {
  const plain = value == null ? null : toPlain(value);
  if (plain == null) return "—";
  const m = PLAIN.exec(plain)!;
  const frac = (m[3] ?? "").padEnd(2, "0");
  const shifted = `${m[1] ?? ""}${m[2]}${frac.slice(0, 2)}.${frac.slice(2) || "0"}`;
  return `${decimal(shifted, dp)}%`;
}

const SYDNEY = "Australia/Sydney";

export function dateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-AU", {
    timeZone: SYDNEY,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function date(iso: string): string {
  return new Intl.DateTimeFormat("en-AU", {
    timeZone: SYDNEY,
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

/** "4 min ago", "3 hours ago", "2 days ago". */
export function age(iso: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} days ago`;
}
