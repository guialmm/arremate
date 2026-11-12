import type { Metadata } from "next";
import { IBM_Plex_Sans, Newsreader } from "next/font/google";
import Link from "next/link";

import "./globals.css";

const plex = IBM_Plex_Sans({ variable: "--font-plex", subsets: ["latin"], weight: ["400", "500", "600"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], weight: ["500", "700"] });

export const metadata: Metadata = {
  title: "Arremate · triagem de licitações",
  description:
    "Lê os editais do Portal Nacional de Contratações Públicas, diz se vale participar e mostra onde está escrito cada requisito.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`${plex.variable} ${newsreader.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="border-b-2 border-tinta">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-10">
            <Link href="/" className="flex items-baseline gap-3">
              <span className="font-serif text-2xl font-bold tracking-wide">Arremate</span>
              <span className="hidden text-xs uppercase tracking-[0.18em] text-apagado sm:inline">triagem de licitações</span>
            </Link>
            <a href="https://github.com/guialmm/arremate" className="text-sm text-apagado underline-offset-4 hover:text-tinta hover:underline">
              Como funciona
            </a>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="mx-auto w-full max-w-7xl px-5 py-8 text-xs text-apagado sm:px-10">
          Dados: Portal Nacional de Contratações Públicas (PNCP). A análise é feita por IA e cada citação é
          conferida no texto do edital; confira sempre o documento oficial. Projeto de portfólio.
        </footer>
      </body>
    </html>
  );
}
