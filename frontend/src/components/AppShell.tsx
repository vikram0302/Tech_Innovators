"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const link = (href: string, label: string) => (
    <Link
      href={href}
      className={`rounded-md px-3 py-1.5 text-sm font-medium ${
        path === href
          ? "bg-emerald-600 text-white"
          : "text-slate-600 hover:bg-slate-100"
      }`}
    >
      {label}
    </Link>
  );
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="text-lg font-semibold text-emerald-600">Claims Audit Workbench</span>
          <nav className="flex gap-2">
            {link("/audit", "Audit")}
            {link("/regulations", "Regulations")}
          </nav>
        </div>
        <div className="h-8 w-8 rounded-full bg-emerald-100 text-center text-sm leading-8 text-emerald-800">
          U
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
