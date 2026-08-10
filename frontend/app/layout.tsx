import type { ReactNode } from "react";
import Link from "next/link";
import { kanit, saira } from "@/lib/fonts";
import HeaderNav from "@/components/HeaderNav";
import PageShell from "@/components/PageShell";
import "./globals.css";

export const metadata = {
  title: "Arena Cacerense",
  description: "Sistema de reservas da Arena Cacerense",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR" className={`${kanit.variable} ${saira.variable}`}>
      <body>
        <header className="ac-header">
          {/* Logo textual — assets do site institucional (mark.png) não estão
              disponíveis neste repo; ver decisão documentada no relatório da T10. */}
          <Link href="/" className="ac-logo">
            ARENA <span>CACERENSE</span>
          </Link>
          <HeaderNav />
        </header>
        <PageShell>{children}</PageShell>
      </body>
    </html>
  );
}
