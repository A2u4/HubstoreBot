"use client";

import { ShieldAlert } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { PageHeader } from "@/components/ui/page-header";

const sections: SectionSpec[] = [
  { title: "AutoMod", fields: [
    { key: "automodEnabled", type: "toggle", label: "Activar AutoMod", description: "Los mensajes que infringen una regla se borran y el autor recibe un aviso." },
  ] },
  { title: "Anti-spam", fields: [
    { key: "antiSpamEnabled", type: "toggle", label: "Detectar spam", description: "Demasiados mensajes en poco tiempo." },
    { key: "antiSpamThreshold", type: "number", label: "Mensajes permitidos", min: 1, max: 50, showIf: (c) => Boolean(c.antiSpamEnabled) },
    { key: "antiSpamInterval", type: "number", label: "Intervalo", min: 1, max: 60, suffix: "seg", showIf: (c) => Boolean(c.antiSpamEnabled) },
    { key: "antiFloodEnabled", type: "toggle", label: "Anti-flood", description: "Mensajes repetidos o con muchas líneas." },
  ] },
  { title: "Mayúsculas", fields: [
    { key: "antiCapsEnabled", type: "toggle", label: "Limitar mayúsculas" },
    { key: "antiCapsThreshold", type: "number", label: "Porcentaje máximo", min: 30, max: 100, suffix: "%", showIf: (c) => Boolean(c.antiCapsEnabled) },
    { key: "antiCapsMinLength", type: "number", label: "Largo mínimo del mensaje", min: 5, max: 500, suffix: "car.", showIf: (c) => Boolean(c.antiCapsEnabled) },
  ] },
  { title: "Enlaces y palabras", fields: [
    { key: "antiLinksEnabled", type: "toggle", label: "Bloquear enlaces" },
    { key: "antiLinksWhitelist", type: "tags", label: "Dominios permitidos", placeholder: "youtube.com, discord.gg/miserver", wide: true,
      showIf: (c) => Boolean(c.antiLinksEnabled) },
    { key: "blacklistEnabled", type: "toggle", label: "Palabras prohibidas" },
    { key: "blacklistedWords", type: "tags", label: "Lista de palabras", placeholder: "Escribe y pulsa Enter", wide: true,
      showIf: (c) => Boolean(c.blacklistEnabled) },
  ] },
  { title: "Exenciones", description: "Administradores y bots siempre están exentos.", fields: [
    { key: "automodExemptRoleIds", type: "roles", label: "Roles exentos" },
    { key: "automodExemptChannelIds", type: "channels", label: "Canales exentos" },
  ] },
];

export default function AutoModPage() {
  return (
    <>
      <PageHeader title="AutoMod" description="Protección automática del chat" icon={<ShieldAlert size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
