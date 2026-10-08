"use client";

import { useTranslations } from "next-intl";
import { Icon } from "@/components/Icon";

export default function WebSourceNotice() {
  const t = useTranslations("chat");
  return (
    <p className="web-source-note" role="note">
      <Icon name="globe" />
      <span>{t("webSourceNotice")}</span>
    </p>
  );
}
