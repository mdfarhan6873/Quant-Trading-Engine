import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JINI // QUANT TERMINAL v2.0",
  description: "Autonomous High-Frequency Quant & Scalping Terminal",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body
        suppressHydrationWarning
        className="min-h-full flex flex-col font-mono bg-[#070A0F] text-[#E2E8F0] selection:bg-[#05B3D0] selection:text-[#070A0F]"
      >
        {children}
      </body>
    </html>
  );
}
