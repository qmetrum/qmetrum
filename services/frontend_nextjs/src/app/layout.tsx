import type { Metadata } from "next";
import { AppProviders } from "@/components/providers/AppProviders";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Qsight — Risk Intelligence by Qmetrum",
  description: "Advisor risk intelligence workstation by Qmetrum",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AppProviders>
          <div className="flex min-h-screen">
            <Sidebar />
            {/* Content area offset by sidebar width (240px default) */}
            <div className="ml-[240px] flex min-h-screen min-w-0 flex-1 flex-col">
              <TopBar />
              <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                {children}
              </main>
            </div>
          </div>
        </AppProviders>
      </body>
    </html>
  );
}
