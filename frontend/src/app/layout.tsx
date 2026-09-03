import type { Metadata } from "next";
import Link from "next/link";
import { Archivo, IBM_Plex_Mono, Public_Sans } from "next/font/google";
import "./globals.css";

const archivo = Archivo({ subsets: ["latin"], variable: "--font-archivo" });
const publicSans = Public_Sans({ subsets: ["latin"], variable: "--font-public-sans" });
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
});

const CONCURRENCY_LABEL = "4 workers · 1 job per document";

export const metadata: Metadata = {
  title: "docpipe",
  description:
    "Queue a stack of PDFs and watch background workers process them in parallel.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${publicSans.variable} ${plexMono.variable}`}
    >
      <body className="min-h-dvh flex flex-col">
        <header className="border-b border-line">
          <div className="mx-auto w-full max-w-5xl px-6 py-4 flex items-baseline justify-between gap-4">
            <Link
              href="/"
              className="font-display text-lg font-extrabold tracking-tight"
            >
              docpipe
            </Link>
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
              {CONCURRENCY_LABEL}
            </p>
          </div>
        </header>

        <main className="flex-1">{children}</main>

        <footer className="border-t border-line">
          <div className="mx-auto w-full max-w-5xl px-6 py-4">
            <p className="font-mono text-[11px] text-muted">
              FastAPI · Redis · Celery · Postgres
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
