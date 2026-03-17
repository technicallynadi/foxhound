import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Foxhound - Product Discovery Engine",
  description:
    "Scout ideas worth building. The AI product discovery engine that scans signals, finds opportunities, and builds improvements.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="relative min-h-screen bg-bg-deep text-text-primary antialiased">
        <div className="fixed inset-0 pointer-events-none" aria-hidden="true">
          <div
            className="absolute w-[800px] h-[600px] rounded-full blur-[120px] opacity-[0.12]"
            style={{
              top: "15%",
              left: "25%",
              background: "radial-gradient(circle, #8B5CF6 0%, transparent 70%)",
            }}
          />
          <div
            className="absolute w-[500px] h-[500px] rounded-full blur-[120px] opacity-[0.08]"
            style={{
              top: "70%",
              left: "75%",
              background: "radial-gradient(circle, #3B82F6 0%, transparent 70%)",
            }}
          />
        </div>
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  );
}
