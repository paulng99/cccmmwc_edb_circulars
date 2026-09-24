"use client";

import { FormEvent, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const t = useTranslations("login");
  const tApp = useTranslations("app");
  const locale = useLocale();
  const { setToken, token } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("000000");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (token) {
    router.replace("/documents");
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await login(username, password);
      setToken(res.access_token);
      router.replace("/documents");
    } catch {
      setError(t("error"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-wrap page-enter">
      <div className="login-stage">
        <aside className="login-hero" aria-hidden={false}>
          <p className="login-eyebrow">{tApp("name")}</p>
          <h1 className="login-hero-title">{tApp("tagline")}</h1>
          <ul className="login-points">
            <li>{t("pointCollect")}</li>
            <li>{t("pointAsk")}</li>
            <li>{t("pointBilingual")}</li>
          </ul>
        </aside>
        <form className="panel login-card" onSubmit={onSubmit}>
          <div className="login-card-top">
            <h2>{t("title")}</h2>
            <Link
              href="/login"
              locale={locale === "zh-HK" ? "en" : "zh-HK"}
              className="login-locale"
            >
              {locale === "zh-HK" ? "EN" : "繁"}
            </Link>
          </div>
          {error ? <div className="error">{error}</div> : null}
          <div className="field">
            <label htmlFor="username">{t("username")}</label>
            <input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div className="field">
            <label htmlFor="password">{t("password")}</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          <button className={`btn${loading ? " is-loading" : ""}`} type="submit" disabled={loading}>
            {t("submit")}
          </button>
          <p className="hint">{t("hint")}</p>
        </form>
      </div>
    </div>
  );
}
