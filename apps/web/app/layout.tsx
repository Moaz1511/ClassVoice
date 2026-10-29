import type { Metadata } from "next";
import { ThemeProvider } from "../components/theme/ThemeProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ClassVoice", template: "%s · ClassVoice" },
  description: "Consent-first academic voice generation for teachers and learning agents.",
};

const themeBootstrap = `
  (() => {
    try {
      const stored = localStorage.getItem('classvoice.theme') || 'system';
      const dark = stored === 'dark' || (stored === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
      document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    } catch (_) { document.documentElement.dataset.theme = 'light'; }
  })();
`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
      <body><ThemeProvider>{children}</ThemeProvider></body>
    </html>
  );
}
