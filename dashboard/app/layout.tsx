import "./globals.css";

export const metadata = {
  title: "Deal-Room — Operator Console",
  description: "Autonomous AI sales-call agent — live control",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
