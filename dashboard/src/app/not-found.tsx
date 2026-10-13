import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="text-center">
        <p className="font-mono text-sm text-muted">404</p>
        <h1 className="mt-2 text-xl font-semibold">Página no encontrada</h1>
        <Link href="/" className="mt-6 inline-block text-sm underline underline-offset-4">Volver al inicio</Link>
      </div>
    </main>
  );
}
