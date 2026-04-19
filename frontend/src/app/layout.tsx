import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title:       "ITR-1 Auto-Fill — AI Tax Assistant",
  description: "Upload Form 16 and let AI file your ITR-1 Sahaj automatically. AY 2024-25.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
