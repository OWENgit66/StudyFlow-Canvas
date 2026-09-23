import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import Link from "next/link";
import { SyncProvider } from "@/components/sync";

export const metadata: Metadata = {
  title: "StudyFlow",
  description: "Your courses, connected. A personal university learning space.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased"><SyncProvider>
        <header className="site-header"><div className="header-inner">
          <Link className="brand" href="/" aria-label="StudyFlow home"><span className="brand-mark" aria-hidden="true">s<span>f</span></span>StudyFlow<span className="brand-period">.</span></Link>
          <nav aria-label="Main navigation"><Link href="/">My courses <span aria-hidden="true">↗</span></Link></nav>
        </div></header>
        <main className="workspace">{children}</main>
        <footer className="site-footer"><span>StudyFlow</span><span>A little structure. More room to learn.</span></footer>
      </SyncProvider></body>
    </html>
  );
}
