import "./globals.css";
import AppShell from "../components/AppShell";

export const metadata = { title: "Aastha CRM", description: "Clinic operations CRM" };

export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="en"><body><AppShell children={children} /></body></html>
}
