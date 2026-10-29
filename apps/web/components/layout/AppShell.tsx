"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { signOut } from "../../lib/auth";
import { ThemeToggle } from "../ui/ThemeToggle";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

const primaryNavigation = [
  { href: "/dashboard", label: "Dashboard", icon: "⌂" },
  { href: "/voices", label: "Voice profiles", icon: "◉" },
  { href: "/studio", label: "Studio", icon: "✦" },
  { href: "/generations", label: "Generations", icon: "▶" },
];

const adminNavigation = [
  { href: "/api-keys", label: "API keys" },
  { href: "/webhooks", label: "Webhooks" },
  { href: "/admin/reports", label: "Reports" },
  { href: "/admin/audit", label: "Audit log" },
];

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();

  function isActive(href: string): boolean {
    return pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
  }

  function handleSignOut() {
    signOut();
    router.replace("/auth/sign-in");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <Link className="brand" href="/dashboard" aria-label="ClassVoice dashboard">
          <span className="brand-mark" aria-hidden="true">CV</span>
          <span>ClassVoice</span>
        </Link>
        <WorkspaceSwitcher />
        <p className="workspace-label">Workspace navigation</p>
        <nav className="nav-list">
          {primaryNavigation.map((item) => (
            <Link className={`nav-link${isActive(item.href) ? " active" : ""}`} href={item.href} key={item.href}>
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="workspace-label admin-label">Workspace tools</p>
        <nav className="nav-list">
          {adminNavigation.map((item) => (
            <Link className={`nav-link${isActive(item.href) ? " active" : ""}`} href={item.href} key={item.href}>
              <span className="nav-placeholder-icon" aria-hidden="true">•</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <Link className="nav-link" href="/settings/profile"><span aria-hidden="true">⚙</span>Settings</Link>
          <button className="nav-link nav-button" type="button" onClick={handleSignOut}><span aria-hidden="true">↪</span>Sign out</button>
        </div>
      </aside>
      <div className="shell-content">
        <header className="topbar">
          <div>
            <span className="eyebrow">Academic voice studio</span>
            <span className="topbar-status"><span className="status-dot" />All systems operational</span>
          </div>
          <div className="topbar-actions"><WorkspaceSwitcher /><ThemeToggle /><button className="avatar" type="button" aria-label="Open account menu">M</button></div>
        </header>
        <nav className="mobile-nav" aria-label="Mobile workspace navigation">
          {primaryNavigation.map((item) => (
            <Link className={`mobile-nav-link${isActive(item.href) ? " active" : ""}`} href={item.href} key={item.href}>{item.label}</Link>
          ))}
        </nav>
        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
