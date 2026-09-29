import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  matcher: ["/", "/(zh-HK|en)/:path*", "/((?!api|_next|_vercel|.*\\..*).*)"],
};
