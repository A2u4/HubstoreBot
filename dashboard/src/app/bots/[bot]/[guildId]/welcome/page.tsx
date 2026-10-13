"use client";

import { Hand, Send } from "lucide-react";
import { useState } from "react";
import { CardEditor } from "@/components/config/card-editor";
import { ConfigEditor, type SectionSpec, useConfigDraft } from "@/components/config/config-editor";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmbedPreview } from "@/components/ui/embed-preview";
import { Tabs } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";

type Kind = "welcome" | "farewell";
const VARS = ["{user}", "{username}", "{tag}", "{server}", "{memberCount}", "{inviter}"];

function sections(kind: Kind): SectionSpec[] {
  const p = kind;
  const isImage = (c: Record<string, unknown>) => Boolean(c[`${p}ImageEnabled`]);
  return [
    { title: kind === "welcome" ? "Bienvenida" : "Despedida", fields: [
      { key: `${p}Enabled`, type: "toggle", label: kind === "welcome" ? "Enviar mensaje de bienvenida" : "Enviar mensaje de despedida" },
      { key: `${p}ChannelId`, type: "channel", label: "Canal" },
      { key: `${p}ImageEnabled`, type: "toggle", label: "Usar tarjeta con imagen", description: "Si está apagado se envía un embed." },
      { key: `${p}Message`, type: "textarea", label: "Mensaje", rows: 3, max: 2000, vars: VARS },
    ] },
    { title: "Embed", description: "Se usa cuando la tarjeta con imagen está desactivada.", fields: [
      { key: `${p}EmbedTitle`, type: "text", label: "Título", max: 256, showIf: (c) => !isImage(c) },
      { key: `${p}EmbedColor`, type: "color", label: "Color", showIf: (c) => !isImage(c) },
      { key: `${p}EmbedDescription`, type: "textarea", label: "Descripción", help: "Vacío = usa el mensaje.", max: 4096, vars: VARS, showIf: (c) => !isImage(c) },
      { key: `${p}EmbedFooter`, type: "text", label: "Pie de página", max: 2048, showIf: (c) => !isImage(c) },
      { key: `${p}EmbedImage`, type: "text", label: "Imagen (URL)", showIf: (c) => !isImage(c) },
      { key: `${p}EmbedThumbnail`, type: "text", label: "Miniatura (URL)", help: "Vacío = avatar del miembro.", showIf: (c) => !isImage(c) },
    ] },
    { title: "Tarjeta", description: "Haz clic en la vista previa para mover el elemento seleccionado.", fields: [
      { key: `${p}CardLayout`, type: "custom", wide: true, showIf: isImage, render: (value, set) => <CardEditor value={value} onChange={set} /> },
    ] },
  ];
}

function Preview({ kind }: { kind: Kind }) {
  const { config } = useConfigDraft();
  const { botName, guildName } = useGuild();
  if (config[`${kind}ImageEnabled`]) return null;
  const fill = (text: unknown) => String(text ?? "").replaceAll("{user}", "@Miembro").replaceAll("{username}", "miembro")
    .replaceAll("{tag}", "miembro").replaceAll("{server}", guildName).replaceAll("{memberCount}", "1.234").replaceAll("{inviter}", "@Invitador");
  return (
    <Card>
      <CardHeader title="Vista previa" />
      <CardBody>
        <EmbedPreview botName={botName} embed={{
          title: fill(config[`${kind}EmbedTitle`] || (kind === "welcome" ? "¡Bienvenido!" : "¡Adiós!")),
          description: fill(config[`${kind}EmbedDescription`] || config[`${kind}Message`]),
          color: (config[`${kind}EmbedColor`] as string) || (kind === "welcome" ? "#57F287" : "#ED4245"),
          footerText: fill(config[`${kind}EmbedFooter`] || (kind === "welcome" ? "Miembro #{memberCount}" : "1.233 miembros restantes")),
          imageUrl: config[`${kind}EmbedImage`] as string, thumbnailUrl: (config[`${kind}EmbedThumbnail`] as string) || null, timestamp: true,
        }} />
      </CardBody>
    </Card>
  );
}

export default function WelcomePage() {
  const { api } = useGuild();
  const [tab, setTab] = useState<Kind | "roles">("welcome");
  const [testing, setTesting] = useState(false);
  const test = async (kind: Kind) => {
    setTesting(true);
    try {
      await apiFetch(`${api}/welcome/test`, { body: { kind } });
      toast.success("Mensaje de prueba enviado (guarda antes los cambios para verlos)");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setTesting(false);
    }
  };
  return (
    <>
      <PageHeader title="Bienvenida" description="Mensajes de entrada y salida, tarjetas con imagen y roles automáticos" icon={<Hand size={18} />}
                  actions={tab !== "roles" ? <Button icon={<Send size={14} />} loading={testing} onClick={() => test(tab)}>Enviar prueba</Button> : undefined} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "welcome", label: "Bienvenida" }, { id: "farewell", label: "Despedida" }, { id: "roles", label: "Roles de entrada" }]} />
      {tab === "roles" ? (
        <ConfigEditor sections={[{ title: "Roles automáticos", description: "Se asignan al entrar (solo roles por debajo del rol del bot).", fields: [
          { key: "joinRoleIds", type: "roles", label: "Roles para miembros", assignableOnly: true },
          { key: "botJoinRoleIds", type: "roles", label: "Roles para bots", assignableOnly: true },
        ] }]} />
      ) : (
        <ConfigEditor key={tab} sections={sections(tab)}><Preview kind={tab} /></ConfigEditor>
      )}
    </>
  );
}
