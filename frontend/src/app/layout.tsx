import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Claims Audit Workbench",
  description: "Evidence-backed claims audit agent for Google hackathon",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
