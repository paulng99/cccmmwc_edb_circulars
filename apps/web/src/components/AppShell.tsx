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
    return <div className="login-wrap">Loading…</div>;
  }

  if (!token || isLogin) {
    return <>{children}</>;
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <strong>{t("app.name")}</strong>
          <span>{t("app.tagline")}</span>
        </div>
        <nav className="nav">
          <Link href="/documents" className={pathname.startsWith("/documents") ? "active" : ""}>
            {t("nav.documents")}
          </Link>
          <Link href="/chat" className={pathname.startsWith("/chat") ? "active" : ""}>
            {t("nav.chat")}
          </Link>
          <Link href="/status" className={pathname.startsWith("/status") ? "active" : ""}>
            {t("nav.status")}
          </Link>
          <Link href="/settings" className={pathname.startsWith("/settings") ? "active" : ""}>
            {t("nav.settings")}
          </Link>
          <button
            type="button"
            onClick={() => router.replace(pathname, { locale: locale === "zh-HK" ? "en" : "zh-HK" })}
          >
            {locale === "zh-HK" ? "EN" : "繁"}
          </button>
          <button type="button" onClick={logout}>
            {username ? `${username} · ${t("nav.logout")}` : t("nav.logout")}
          </button>
        </nav>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}
