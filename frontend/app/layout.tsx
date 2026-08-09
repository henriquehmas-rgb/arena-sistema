export const metadata = {
  title: "Arena Cacerense",
  description: "Sistema de reservas da Arena Cacerense",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
