"use client";

import { useTranslations, useLocale } from "next-intl";
import type { ReactNode } from "react";
import { Link, usePathname, useRouter } from "@/i18n/routing";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { Icon, type IconName } from "@/components/Icon";

export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { token, username, logout, ready } = useAuth();
  const { theme, toggle } = useTheme();

  const isLogin = pathname.includes("/login");

  if (!ready) {
    return (
      <div className="boot" aria-busy="true">
        <div className="boot-inner">
          <span className="spinner lg" />
          <span>{t("app.name")}</span>
        </div>
      </div>
    );
  }

  if (!token || isLogin) {
    return <>{children}</>;
  }

  const links: { href: string; label: string; match: string; icon: IconName }[] = [
    { href: "/documents", label: t("nav.documents"), match: "/documents", icon: "file-text" },
    { href: "/chat", label: t("nav.chat"), match: "/chat", icon: "message-square" },
    { href: "/status", label: t("nav.status"), match: "/status", icon: "activity" },
    { href: "/settings", label: t("nav.settings"), match: "/settings", icon: "settings" },
  ];

  const otherLocale = locale === "zh-HK" ? "en" : "zh-HK";
  const otherLocaleLabel = locale === "zh-HK" ? "English" : "繁體中文";
  const otherLocaleShort = locale === "zh-HK" ? "EN" : "繁";
  const themeLabel = theme === "dark" ? t("nav.themeLight") : t("nav.themeDark");

  const switchLocale = () => router.replace(pathname, { locale: otherLocale });

  const brand = (
    <Link href="/documents" className="brand" aria-label={t("app.name")}>
      <span className="brand-mark">
        <Icon name="book-open" />
      </span>
      <span className="brand-text">
        <strong>{t("app.name")}</strong>
        <span>{t("app.taglineShort")}</span>
      </span>
    </Link>
  );

  return (
    <div className="app">
      <aside className="sidebar">
        {brand}
        <nav className="sidenav" aria-label={t("nav.main")}>
          <div className="sidenav-label">{t("nav.sectionWorkspace")}</div>
          {links.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={pathname.startsWith(item.match) ? "active" : ""}
              aria-current={pathname.startsWith(item.match) ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-card">
            <span className="avatar" aria-hidden>
              {(username || "?").slice(0, 1)}
            </span>
            <div>
              <strong>{username || "—"}</strong>
              <span>{t("nav.role")}</span>
            </div>
          </div>
          <div className="util-row">
            <button type="button" className="util-btn" onClick={switchLocale} title={otherLocaleLabel}>
              <Icon name="languages" />
              <span>{otherLocaleShort}</span>
            </button>
            <button type="button" className="util-btn" onClick={toggle} title={themeLabel} aria-label={themeLabel}>
              <Icon name={theme === "dark" ? "sun" : "moon"} />
            </button>
            <button type="button" className="util-btn danger" onClick={logout} title={t("nav.logout")} aria-label={t("nav.logout")}>
              <Icon name="log-out" />
            </button>
          </div>
        </div>
      </aside>

      <header className="mobile-header">
        {brand}
        <div className="util-row">
          <button type="button" className="util-btn" onClick={switchLocale} title={otherLocaleLabel} aria-label={otherLocaleLabel}>
            <Icon name="languages" />
            <span>{otherLocaleShort}</span>
          </button>
          <button type="button" className="util-btn" onClick={toggle} title={themeLabel} aria-label={themeLabel}>
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
          <button type="button" className="util-btn danger" onClick={logout} title={t("nav.logout")} aria-label={t("nav.logout")}>
            <Icon name="log-out" />
          </button>
        </div>
      </header>

      <main className="main">{children}</main>

      <nav className="tabbar" aria-label={t("nav.main")}>
        {links.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={pathname.startsWith(item.match) ? "active" : ""}
            aria-current={pathname.startsWith(item.match) ? "page" : undefined}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
