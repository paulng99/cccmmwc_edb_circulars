"use client";

import { FormEvent, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Icon } from "@/components/Icon";

export default function LoginPage() {
  const t = useTranslations("login");
  const tApp = useTranslations("app");
  const locale = useLocale();
  const { setToken, token } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("000000");
  const [showPassword, setShowPassword] = useState(false);
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

  const otherLocale = locale === "zh-HK" ? "en" : "zh-HK";
  const year = new Date().getFullYear();

  return (
    <div className="auth">
      <aside className="auth-side">
        <div className="auth-brand">
          <span className="brand-mark">
            <Icon name="book-open" />
          </span>
          {tApp("name")}
        </div>

        <div className="auth-hero">
          <h1>{tApp("tagline")}</h1>
          <p>{t("heroLead")}</p>
          <ul className="auth-points">
            <li>
              <span className="auth-point-icon">
                <Icon name="refresh-cw" />
              </span>
              <div>
                <strong>{t("pointCollect")}</strong>
                <span>{t("pointCollectDesc")}</span>
              </div>
            </li>
            <li>
              <span className="auth-point-icon">
                <Icon name="sparkles" />
              </span>
              <div>
                <strong>{t("pointAsk")}</strong>
                <span>{t("pointAskDesc")}</span>
              </div>
            </li>
            <li>
              <span className="auth-point-icon">
                <Icon name="languages" />
              </span>
              <div>
                <strong>{t("pointBilingual")}</strong>
                <span>{t("pointBilingualDesc")}</span>
              </div>
            </li>
          </ul>
        </div>

        <p className="auth-foot">
          © {year} {tApp("name")} · {t("footNote")}
        </p>
      </aside>

      <main className="auth-main">
        <form className="card auth-card" onSubmit={onSubmit}>
          <div className="auth-mobile-brand">
            <span className="brand-mark">
              <Icon name="book-open" />
            </span>
            <strong>{tApp("name")}</strong>
          </div>

          <div className="auth-card-head">
            <div>
              <h2>{t("title")}</h2>
              <p>{t("subtitle")}</p>
            </div>
            <Link href="/login" locale={otherLocale} className="btn secondary sm">
              <Icon name="languages" />
              {locale === "zh-HK" ? "EN" : "繁"}
            </Link>
          </div>

          {error ? (
            <div className="alert danger" role="alert" style={{ marginBottom: "1rem" }}>
              <Icon name="alert-circle" />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="username">{t("username")}</label>
            <div className="input-wrap">
              <Icon name="user" />
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
          </div>

          <div className="field">
            <label htmlFor="password">{t("password")}</label>
            <div className="input-wrap has-trailing">
              <Icon name="lock" />
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="input-trailing"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? t("hidePassword") : t("showPassword")}
                title={showPassword ? t("hidePassword") : t("showPassword")}
              >
                <Icon name={showPassword ? "eye-off" : "eye"} />
              </button>
            </div>
          </div>

          <button className={`btn lg block${loading ? " is-loading" : ""}`} type="submit" disabled={loading}>
            {loading ? <span className="spinner" /> : <Icon name="log-out" style={{ transform: "rotate(180deg)" }} />}
            {loading ? t("submitting") : t("submit")}
          </button>

          <p className="auth-hint">{t("hint")}</p>
        </form>
      </main>
    </div>
  );
}
