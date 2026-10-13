import type { Metadata, Viewport } from "next";
import { Toaster } from "@/components/ui/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Markets Dashboard", template: "%s · Markets Dashboard" },
  description: "Panel de administración de los bots Markets",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#000000", colorScheme: "dark" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="min-h-screen font-sans">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
