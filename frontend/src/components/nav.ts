// The 14 sections from the PRD (12.1), grouped by what the user is doing.
// `ready: false` marks sections whose back end isn't built yet.

export interface NavItem {
  href: string;
  label: string;
  ready: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "My money",
    items: [
      { href: "/", label: "Dashboard", ready: true },
      { href: "/portfolios", label: "My portfolios", ready: true },
      { href: "/holdings", label: "Holdings", ready: true },
      { href: "/transactions", label: "Transactions", ready: true },
      { href: "/dividends", label: "Dividends", ready: false },
    ],
  },
  {
    label: "Research",
    items: [
      { href: "/markets", label: "Markets", ready: false },
      { href: "/watchlists", label: "Watchlists", ready: false },
      { href: "/research", label: "Stock research", ready: false },
      { href: "/assistant", label: "AI investment assistant", ready: false },
    ],
  },
  {
    label: "Analysis",
    items: [
      { href: "/analytics", label: "Analytics", ready: false },
      { href: "/risk", label: "Risk management", ready: false },
      { href: "/reports", label: "Reports", ready: false },
    ],
  },
  {
    label: "Practice",
    items: [{ href: "/paper-trading", label: "Paper trading", ready: false }],
  },
  {
    label: "",
    items: [{ href: "/settings", label: "Settings", ready: true }],
  },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
