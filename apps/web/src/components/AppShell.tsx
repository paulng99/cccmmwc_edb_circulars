"use client";

import { useTranslations, useLocale } from "next-intl";
import type { ReactNode } from "react";
import { Link, usePathname, useRouter } from "@/i18n/routing";
import { useAuth } from "@/lib/auth";

export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { token, username, logout, ready } = useAuth();

  const isLogin = pathname.includes("/login");

  if (!ready) {
    return (
      <div className="login-wrap page-enter" aria-busy="true">
        <div className="panel login-card" style={{ textAlign: "center" }}>
          <div className="login-brand" style={{ borderBottom: 0, marginBottom: 0, paddingBottom: 0 }}>
            <strong>{t("app.name")}</strong>
            <span>{t("app.tagline")}</span>
          </div>
        </div>
      </div>
    );
  }

  if (!token || isLogin) {
    return <>{children}</>;
  }

  const links = [
    { href: "/documents", label: t("nav.documents"), match: "/documents" },
    { href: "/chat", label: t("nav.chat"), match: "/chat" },
    { href: "/status", label: t("nav.status"), match: "/status" },
    { href: "/settings", label: t("nav.settings"), match: "/settings" },
  ] as const;

  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/documents" className="brand">
          <strong>{t("app.name")}</strong>
          <span>{t("app.tagline")}</span>
        </Link>
        <nav className="nav" aria-label="Main">
          <div className="nav-primary" role="list">
            {links.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                role="listitem"
                className={pathname.startsWith(item.match) ? "active" : ""}
              >
                {item.label}
              </Link>
            ))}
          </div>
          <div className="nav-utils">
            <button
              type="button"
              className="nav-util"
              onClick={() =>
                router.replace(pathname, { locale: locale === "zh-HK" ? "en" : "zh-HK" })
              }
            >
              {locale === "zh-HK" ? "EN" : "繁"}
            </button>
            <button type="button" className="nav-util nav-util-logout" onClick={logout}>
              {username ? `${username} · ${t("nav.logout")}` : t("nav.logout")}
            </button>
          </div>
        </nav>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
