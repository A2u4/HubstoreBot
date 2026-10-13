"use client";

import { Send, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { ConfigEditor, type SectionSpec, useConfigDraft } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmbedPreview } from "@/components/ui/embed-preview";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";

const sections: SectionSpec[] = [
  { title: "Panel de verificación", description: "Los miembros pulsan «Verificarme» y reciben el rol. Con captcha deben escribir el código de una imagen (3 intentos).", fields: [
    { key: "verificationEnabled", type: "toggle", label: "Activar verificación" },
    { key: "verificationMode", type: "select", label: "Modo", options: [{ value: "button", label: "Botón (un clic)" }, { value: "captcha", label: "Captcha de imagen" }] },
    { key: "verificationChannelId", type: "channel", label: "Canal del panel" },
    { key: "verificationRoleId", type: "role", label: "Rol al verificarse", assignableOnly: true },
    { key: "verificationRemoveRoleId", type: "role", label: "Rol a quitar (opcional)", assignableOnly: true, help: "Ej. «No verificado»." },
    { key: "verificationPanelTitle", type: "text", label: "Título del panel", max: 256 },
    { key: "verificationPanelMessage", type: "textarea", label: "Texto del panel", max: 4000, rows: 3 },
  ] },
  { title: "Seguridad del Market", description: "Registro externo con detección de evasión de sanciones (/verificar). Requiere HTTPS en DASHBOARD_URL.", fields: [
    { key: "marketVerificationEnabled", type: "toggle", label: "Activar registro del Market", description: "Muestra /verificar en el servidor." },
    { key: "marketVerificationRoleId", type: "role", label: "Rol tras el registro", assignableOnly: true },
    { key: "marketVerificationLogChannelId", type: "channel", label: "Canal de alertas" },
    { key: "marketVerificationRetentionDays", type: "number", label: "Retención de identificadores", min: 1, max: 3650, suffix: "días" },
    { key: "marketVpnCheckEnabled", type: "toggle", label: "Detectar VPN / proxy", description: "Consulta temporal a IPinfo (requiere IPINFO_TOKEN)." },
    { key: "marketVpnPolicy", type: "select", label: "Ante una VPN", options: [{ value: "review", label: "Enviar a revisión" }, { value: "block", label: "Rechazar" }],
      showIf: (c) => Boolean(c.marketVpnCheckEnabled) },
    { key: "marketBlockedNetworkAction", type: "select", label: "Red con sanción activa", options: [
      { value: "deny", label: "Rechazar el registro" }, { value: "ban", label: "Ban automático (nunca a staff)" }] },
  ] },
];

function PanelPreview() {
  const { config, saved } = useConfigDraft();
  const { api, botName } = useGuild();
  const [busy, setBusy] = useState(false);
  const publish = async () => {
    setBusy(true);
    try {
      await apiFetch(`${api}/verification/panel`, { body: {} });
      toast.success("Panel publicado");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader title="Vista previa" description="Publica tras guardar; si ya existe, se actualiza en el mismo mensaje."
                  actions={<Button size="sm" variant="primary" icon={<Send size={13} />} loading={busy}
                                   disabled={!saved.verificationChannelId || !saved.verificationRoleId} onClick={publish}>Publicar panel</Button>} />
      <CardBody>
        <EmbedPreview botName={botName} embed={{ title: String(config.verificationPanelTitle ?? ""), description: String(config.verificationPanelMessage ?? ""),
                                                 color: "#FFFFFF", footerText: config.verificationMode === "captcha" ? "Captcha de imagen" : "Verificación con un clic" }} />
        <div className="mt-2 pl-12"><span className="inline-flex h-8 items-center rounded-md bg-[#248046] px-3 text-sm text-white">✅ Verificarme</span></div>
      </CardBody>
    </Card>
  );
}

export default function VerificationPage() {
  return (
    <>
      <PageHeader title="Verificación" description="Protege el servidor de cuentas automáticas y evasores de sanciones" icon={<ShieldCheck size={18} />} />
      <ConfigEditor sections={sections}><PanelPreview /></ConfigEditor>
    </>
  );
}
