import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Exclude static metadata icons so unauthenticated clients can fetch them
  // without a locale prefix or login redirect (next-intl would otherwise rewrite
  // extensionless /icon and /apple-icon into /zh-HK/...).
  matcher: [
    "/",
    "/(zh-HK|en)/:path*",
    "/((?!api|_next|_vercel|icon$|apple-icon$|.*\\..*).*)",
  ],
};
