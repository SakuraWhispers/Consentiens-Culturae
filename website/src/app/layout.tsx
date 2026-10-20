import type { Metadata } from "next";
import { EB_Garamond, Poppins } from "next/font/google";
import "./globals.css";

// The mock's serif (headlines + body) and the wordmark's geometric sans.
const ebGaramond = EB_Garamond({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-eb-garamond",
});
const poppins = Poppins({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-poppins",
});

export const metadata: Metadata = {
  title: "Consentiens Culturae",
  description:
    "Compare three product concepts with Qloo culture-affinity evidence, transparent scoring, and sensitivity analysis.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${ebGaramond.className} ${poppins.variable} antialiased bg-cream text-ink`}
      >
        {children}
      </body>
    </html>
  );
}
