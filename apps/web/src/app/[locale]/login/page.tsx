"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const t = useTranslations("login");
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
    <div className="login-wrap">
      <form className="panel login-card" onSubmit={onSubmit}>
        <h1>{t("title")}</h1>
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
        <button className="btn" type="submit" disabled={loading}>
          {t("submit")}
        </button>
        <p className="hint">{t("hint")}</p>
      </form>
    </div>
  );
}
