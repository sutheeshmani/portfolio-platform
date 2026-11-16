import type { Metadata } from "next";
import { Hanken_Grotesk } from "next/font/google";

import "./globals.css";

const hanken = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Portfolio", template: "%s – Portfolio" },
  description: "Personal ASX and US share portfolio, valued in AUD.",
  robots: { index: false, follow: false },
};

// Applies the saved or system theme before first paint, so pages don't flash.
const themeScript = `(function(){try{var t=localStorage.getItem("pp.theme");var d=t?t==="dark":window.matchMedia("(prefers-color-scheme: dark)").matches;if(d)document.documentElement.classList.add("dark");}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-AU" className={hanken.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen bg-paper text-ink">{children}</body>
    </html>
  );
}
