"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const t = useTranslations();
  const { token, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    router.replace(token ? "/documents" : "/login");
  }, [ready, token, router]);

  return (
    <div className="boot" aria-busy="true">
      <div className="boot-inner">
        <span className="spinner lg" />
        <span>{t("app.name")}</span>
      </div>
    </div>
  );
}
