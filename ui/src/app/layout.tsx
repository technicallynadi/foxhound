import type { Metadata } from "next";
import Link from "next/link";
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
  description:
    "Your personal career agent. Foxhound finds matching jobs, fills out real application forms, tracks every submission, and follows up with hiring managers.",
  keywords: [
    "job search",
    "career agent",
    "AI",
    "auto apply",
    "job applications",
    "career changer",
  ],
  openGraph: {
    title: "Foxhound — Stop Applying. Start Interviewing.",
    description:
      "Your personal career agent. Upload your resume, find matching jobs, and let Foxhound apply for you.",
    type: "website",
    siteName: "Foxhound",
    url: "https://usefoxhound.com",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Foxhound — Stop Applying. Start Interviewing.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Foxhound — Stop Applying. Start Interviewing.",
    description:
      "Personal career agent that finds jobs, applies with precision, and proves every submission with a screenshot.",
    images: ["/opengraph-image"],
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
  },
  metadataBase: new URL("https://usefoxhound.com"),
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}
    >
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

        <footer style={{
          marginTop: 80,
          paddingBottom: 32,
          textAlign: 'center',
          position: 'relative',
          zIndex: 1,
        }}>
          <p style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--t3)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            lineHeight: 1.8,
          }}>
            Powered by{' '}
            <Link href="/" style={{
              color: 'var(--vl)',
              borderBottom: '1px solid rgba(139,92,246,0.2)',
              textDecoration: 'none',
            }}>
              Foxhound
            </Link>
          </p>
        </footer>
      </body>
    </html>
  );
}
