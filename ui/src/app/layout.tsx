import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import AgentProvider from "@/components/agent/AgentProvider";
import AgentWidget from "@/components/agent/AgentWidget";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Foxhound — Stop Applying. Start Interviewing.",
  description: "Your personal career agent. Foxhound finds matching jobs, fills out applications, and proves every submission with a screenshot.",
  openGraph: {
    title: "Foxhound — Stop Applying. Start Interviewing.",
    description: "Your personal career agent. Upload your resume, find matching jobs, and let Foxhound apply for you. Free to browse.",
    type: "website",
  },
  metadataBase: new URL("https://usefoxhound.com"),
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}>
      <head>
        <meta name="theme-color" content="#080808" />
      </head>
      <body>
        {/* Global textures — present on all pages */}
        <div className="grid-bg" />
        <div className="grain" />
        <div className="dot-track">
          {Array.from({ length: 13 }, (_, i) => (
            <span key={i} />
          ))}
        </div>

        <AuthProvider>
          <AgentProvider>
            {children}
            <AgentWidget />
          </AgentProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
