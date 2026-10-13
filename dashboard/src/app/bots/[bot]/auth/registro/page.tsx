import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { botCall } from "@/lib/server/bot-api";
import { getBot } from "@/lib/server/bots";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Verificación", referrer: "no-referrer" };

const STATES: Record<string, { title: string; text: string }> = {
  verificado: { title: "Registro completado", text: "Tu cuenta de Discord quedó verificada. Ya puedes cerrar esta página y volver al servidor." },
  bloqueado: { title: "Registro no autorizado", text: "La verificación fue detenida por una regla de seguridad. Contacta al staff si consideras que se trata de un error." },
  baneado: { title: "Acceso bloqueado", text: "La cuenta fue bloqueada automáticamente porque la red coincide con una sanción activa. Contacta al staff si compartes esta conexión y consideras que se trata de un error." },
  vpn_bloqueada: { title: "Desactiva la VPN o el proxy", text: "La red fue identificada como VPN, proxy, Tor o relay. Desactívalo y vuelve a realizar la verificación." },
  revision: { title: "Verificación en revisión", text: "La red necesita una revisión del staff antes de asignar el acceso. No necesitas repetir el proceso." },
  no_miembro: { title: "No estás en el servidor", text: "Entra al servidor con esta misma cuenta de Discord y vuelve a intentarlo." },
  desactivado: { title: "Verificación no disponible", text: "El staff todavía no ha activado el registro del Market." },
  error: { title: "No se pudo completar", text: "Ocurrió un error temporal. Espera un momento y vuelve a intentarlo." },
};

function Result({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-xl border border-line-strong p-5">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-3 leading-relaxed text-fg-2">{text}</p>
    </div>
  );
}

/** Public Market registration page (same URL as v1: /bots/<bot>/auth/registro?sesion=<token>). */
export default async function Registration({ params, searchParams }: {
  params: Promise<{ bot: string }>; searchParams: Promise<Record<string, string | undefined>>;
}) {
  const bot = getBot((await params).bot);
  if (!bot) notFound();
  const query = await searchParams;
  const info = await botCall<{ secure: boolean; brand: string }>(bot, "/internal/market/session", { body: {} })
    .catch(() => ({ secure: false, brand: bot.name }));
  const status = query.estado ? STATES[query.estado] : undefined;
  const session = query.sesion && /^[A-Za-z0-9_-]{40,100}$/.test(query.sesion) ? query.sesion : undefined;

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="card w-full max-w-xl p-8">
        <p className="mb-5 text-xs font-medium uppercase tracking-[0.2em] text-muted">{info.brand} · Seguridad</p>
        {status ? <Result {...status} /> : !info.secure ? (
          <Result title="HTTPS requerido" text="El registro está protegido y no puede activarse sobre una conexión HTTP. El administrador debe configurar un dominio con HTTPS." />
        ) : !session ? (
          <Result title="Enlace requerido" text="Vuelve a Discord y pulsa el botón «Verificar ahora». Recibirás un enlace privado que vence en 10 minutos." />
        ) : (
          <>
            <h1 className="text-2xl font-semibold">Verificación del Market</h1>
            <p className="mt-3 leading-relaxed text-fg-2">Confirma tu cuenta de Discord para acceder de forma segura a {info.brand}.</p>
            <div className="my-6 rounded-xl border border-line bg-surface-2 p-4">
              <strong className="text-sm">Protección y privacidad</strong>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                Usaremos un identificador protegido derivado de tu dirección de red para detectar evasión de sanciones. La dirección original no se
                guarda ni se muestra al staff. Si la detección de VPN está activada, la dirección se consulta temporalmente con IPinfo para identificar
                VPN, proxy, Tor, relay o alojamiento. El identificador se elimina después del periodo de retención configurado, salvo que esté asociado
                a una sanción activa.
              </p>
            </div>
            <form method="post" action={`/bots/${bot.id}/auth/registro/iniciar`}>
              <input type="hidden" name="sesion" value={session} />
              <label className="flex items-start gap-3 text-sm leading-relaxed text-fg-2">
                <input type="checkbox" name="consentimiento" value="acepto" required className="mt-1 accent-white" />
                Entiendo y acepto este uso de seguridad.
              </label>
              <button type="submit" className="mt-5 h-11 w-full rounded-lg bg-fg text-sm font-semibold text-bg hover:bg-fg-2">Completar verificación</button>
            </form>
          </>
        )}
        <p className="mt-6 text-xs text-faint">Nunca compartas códigos ni contraseñas con otra persona.</p>
      </div>
    </main>
  );
}
