/**
 * app/layout.tsx
 *
 * Root layout for Personal AI Learning Assistant.
 *
 * Includes:
 *  - Google Identity Services script (afterInteractive — only needed on login page)
 *  - Theme initialization inline script (beforeInteractive-equivalent via dangerouslySetInnerHTML)
 *    to read localStorage and apply data-theme + .dark class BEFORE first paint,
 *    eliminating any flash of wrong theme.
 *  - Navbar on every page
 */

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import Navbar from "../../components/Navbar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Personal AI Learning Assistant",
  description:
    "Grounded RAG study companion — ask questions from your own notes with verified page citations and adaptive quizzes.",
};

/**
 * Inline script executed synchronously before React hydrates.
 * Reads the saved theme from localStorage and applies it immediately,
 * preventing a flash of the wrong theme on page load.
 */
const themeInitScript = `
(function() {
  try {
    var saved = localStorage.getItem('app-theme');
    var theme = (saved === 'light' || saved === 'dark' || saved === 'green')
      ? saved
      : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark' || theme === 'green') {
      document.documentElement.classList.add('dark');
    }
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Theme init: runs before React hydrates to prevent theme flash */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />

        {/* Google Identity Services — loaded after interaction (login page only uses it) */}
        <Script
          src="https://accounts.google.com/gsi/client"
          strategy="afterInteractive"
        />
      </head>
      <body className="min-h-full flex flex-col" suppressHydrationWarning>
        <Navbar />
        <div className="flex-1 flex flex-col">{children}</div>
      </body>
    </html>
  );
}
