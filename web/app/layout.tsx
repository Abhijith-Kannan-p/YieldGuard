import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans_Devanagari, Noto_Sans_Kannada } from "next/font/google";
import "./globals.css";

// Latin text in Inter; Kannada and Hindi glyphs fall through to the Noto families
// (the font stack in globals.css lists all three). Self-hosted by next/font at build time.
const inter = Inter({ subsets: ["latin"], variable: "--font-latin", display: "swap" });
const kannada = Noto_Sans_Kannada({ subsets: ["kannada"], variable: "--font-kannada", display: "swap" });
const devanagari = Noto_Sans_Devanagari({ subsets: ["devanagari"], variable: "--font-devanagari", display: "swap" });

export const metadata: Metadata = {
  title: "YieldGuard – From sky to soil, every season",
  description:
    "Field-status dashboard for Karnataka farmers: live weather, rainfall and soil advice in English, Hindi and Kannada.",
};

export const viewport: Viewport = {
  themeColor: "#111111",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${kannada.variable} ${devanagari.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
