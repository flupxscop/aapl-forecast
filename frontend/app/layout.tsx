import type { Metadata } from "next";
import { Noto_Sans_Thai, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

const latin = Plus_Jakarta_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-latin" });
const thai = Noto_Sans_Thai({ subsets: ["thai"], weight: ["400", "500", "600", "700"], variable: "--font-thai" });

export const metadata: Metadata = {
  title: "Meridian — Stock Forecast",
  description: "ประมาณการราคาหุ้น Apple, NVIDIA, Samsung, Meta และ SpaceX ด้วยแบบจำลองอนุกรมเวลา",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th" className={`${latin.variable} ${thai.variable}`}>
      <body>{children}</body>
    </html>
  );
}
