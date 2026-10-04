import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "QuantBacktest | Motor Agnóstico",
  description: "Plataforma minimalista de análisis y backtesting cuantitativo híbrido.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="bg-white">
      <body className="bg-white text-zinc-900 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
