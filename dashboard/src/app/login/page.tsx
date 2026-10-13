import Link from "next/link";
import { listBots } from "@/lib/server/bots";

const ERRORS: Record<string, string> = {
  rate_limited: "Demasiados intentos. Espera un minuto y vuelve a intentarlo.",
  invalid_state: "La sesión de inicio expiró o no es válida. Inténtalo de nuevo.",
  no_code: "Discord no devolvió un código de acceso.",
  denied: "Cancelaste la autorización en Discord.",
  oauth_code_invalid: "El código de Discord ya fue usado o expiró. Inténtalo de nuevo.",
  token_exchange: "No se pudo validar el acceso con Discord.",
  user_fetch: "No se pudo obtener tu usuario de Discord.",
  not_configured: "El inicio de sesión no está configurado (falta CLIENT_ID / CLIENT_SECRET del bot).",
  unknown: "Ocurrió un error inesperado al iniciar sesión.",
};

export default async function Login({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const params = await searchParams;
  const bots = listBots();
  const bot = bots.find((b) => b.id === params.bot)?.id ?? bots[0]?.id ?? "";
  const next = params.next && params.next.startsWith("/") && !params.next.startsWith("//") ? params.next : undefined;
  const href = `/api/auth/login?bot=${bot}${next ? `&next=${encodeURIComponent(next)}` : ""}`;
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="card w-full max-w-sm p-8">
        <p className="text-xs font-medium uppercase tracking-[0.25em] text-muted">Markets</p>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">Inicia sesión</h1>
        <p className="mt-2 text-sm text-muted">Usamos tu cuenta de Discord para comprobar qué servidores puedes administrar.</p>
        {params.error && (
          <div className="mt-5 rounded-lg border border-line-strong bg-surface-2 px-3 py-2.5 text-sm text-fg-2">
            {ERRORS[params.error] ?? ERRORS.unknown}
          </div>
        )}
        <a href={href} className="mt-6 flex h-10 w-full items-center justify-center rounded-lg bg-fg text-sm font-medium text-bg hover:bg-fg-2">
          Continuar con Discord
        </a>
        <Link href="/" className="mt-4 block text-center text-xs text-muted hover:text-fg">Volver</Link>
      </div>
    </main>
  );
}
