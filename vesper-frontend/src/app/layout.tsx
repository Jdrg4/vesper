import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { APP_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: {
    default: APP_NAME,
    template: `%s — ${APP_NAME}`,
  },
  description: "SaaS que vigila tus repos GitHub y te abre PRs autónomos.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: APP_NAME,
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // suppressHydrationWarning: next-themes reescribe className y color-scheme en
  // <html> antes de hidratar, lo que provocaba un hydration mismatch en cada
  // carga. Es el patron que documenta la propia libreria.
  return (
    <html lang="es" className="dark h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
