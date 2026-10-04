import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

// app/icon.svg, app/icon.png, and app/apple-icon.png are served via App Router
// file conventions. Next only auto-links one "icon.*" extension in <head>, so
// declare all three here so SVG (primary), PNG fallback, and apple-touch-icon
// all appear for the login page and every locale route.
export const metadata: Metadata = {
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon.png", type: "image/png", sizes: "32x32" },
    ],
    apple: [{ url: "/apple-icon.png", type: "image/png", sizes: "180x180" }],
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
