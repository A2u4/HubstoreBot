"use client";

import { ArrowLeftRight, Check } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { Spinner } from "@/components/ui/misc";
import { confirm } from "@/components/ui/modal";
import { PageHeader } from "@/components/ui/page-header";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { type ChannelInfo, CHANNEL, useGuild } from "@/lib/client/guild";
import { CLONE_SECTIONS } from "@/lib/clone-sections";

interface Guild { id: string; name: string; botPresent: boolean }
interface Panel { id: string; name: string; buttonLabel: string; groupEmbedTitle: string | null; groupEmbedDescription: string | null; groupEmbedColor: string | null }

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
            className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm ${on ? "border-fg bg-fg text-bg" : "border-line hover:border-line-strong"}`}>
      {on && <Check size={13} />}{children}
    </button>
  );
}

export default function MigrationPage() {
  const { api, bot, guildId } = useGuild();
  const guilds = useApi<Guild[]>(`/api/bots/${bot}/guilds`);
  const panels = useApi<Panel[]>(`${api}/tickets/panels`);
  const [target, setTarget] = useState("");
  const targetMeta = useApi<{ channels: ChannelInfo[] }>(target ? `/api/bots/${bot}/guilds/${target}/meta` : null);
  const [sections, setSections] = useState<string[]>([]);
  const [panelIds, setPanelIds] = useState<string[]>([]);
  const [channelId, setChannelId] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const others = (guilds.data ?? []).filter((g) => g.botPresent && g.id !== guildId);
  const toggle = (list: string[], id: string, max = Infinity) => list.includes(id) ? list.filter((x) => x !== id) : list.length < max ? [...list, id] : list;

  const migrate = async () => {
    const targetName = others.find((g) => g.id === target)?.name ?? target;
    if (!(await confirm({ title: "Migrar configuración", message: `Se sobrescribirán ${sections.length} sección(es) en «${targetName}»${panelIds.length ? ` y se publicarán ${panelIds.length} panel(es) de tickets` : ""}.`, confirmLabel: "Migrar" }))) return;
    setBusy(true);
    try {
      let count = 0;
      if (sections.length) count += (await apiFetch<{ cloned: number }>(`${api}/config/clone`, { body: { targetGuildId: target, sections } })).cloned;
      if (panelIds.length) {
        const first = panels.data?.find((p) => p.id === panelIds[0]);
        await apiFetch(`${api}/tickets/panels/cross-deploy`, { body: {
          sourcePanelIds: panelIds, targetGuildId: target, channelId, embedTitle: first?.groupEmbedTitle || "Sistema de Tickets",
          embedDescription: first?.groupEmbedDescription || "", embedColor: first?.groupEmbedColor || "#FFFFFF" } });
        count += panelIds.length;
      }
      setResult(`Migración completada hacia «${targetName}»: ${count} elementos.`);
      toast.success("Migración completada");
    } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Migración" description="Copia la configuración y los paneles de tickets a otro servidor de este bot" icon={<ArrowLeftRight size={18} />} />
      {guilds.loading ? <Spinner /> : (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Servidor destino" description="Solo aparecen servidores donde está el bot y tienes permiso de gestión." />
            <CardBody><Select value={target} placeholder="Elegir servidor..." options={others.map((g) => ({ value: g.id, label: g.name }))} onChange={(v) => { setTarget(v); setChannelId(""); }} /></CardBody>
          </Card>
          <Card>
            <CardHeader title="Secciones de configuración" actions={<Button size="sm" variant="ghost" onClick={() => setSections(sections.length ? [] : Object.keys(CLONE_SECTIONS))}>{sections.length ? "Ninguna" : "Todas"}</Button>} />
            <CardBody className="flex flex-wrap gap-2">
              {Object.entries(CLONE_SECTIONS).map(([id, s]) => <Chip key={id} on={sections.includes(id)} onClick={() => setSections(toggle(sections, id))}>{s.label}</Chip>)}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Paneles de tickets" description="Se copian al destino y se publican juntos (máximo 5)." />
            <CardBody className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {(panels.data ?? []).map((p) => <Chip key={p.id} on={panelIds.includes(p.id)} onClick={() => setPanelIds(toggle(panelIds, p.id, 5))}>{p.name}</Chip>)}
                {!panels.data?.length && <p className="text-sm text-muted">Este servidor no tiene paneles.</p>}
              </div>
              {panelIds.length > 0 && (
                <Field label="Canal en el servidor destino">
                  <Select value={channelId} placeholder={target ? "Elegir canal..." : "Primero elige el servidor"}
                          options={(targetMeta.data?.channels ?? []).filter((c) => c.type === CHANNEL.text || c.type === CHANNEL.news).map((c) => ({ value: c.id, label: `# ${c.name}` }))}
                          onChange={setChannelId} />
                </Field>
              )}
            </CardBody>
          </Card>
          <div className="flex items-center gap-4">
            <Button variant="primary" loading={busy} disabled={!target || (!sections.length && !panelIds.length) || (panelIds.length > 0 && !channelId)} onClick={migrate}>Migrar</Button>
            {result && <span className="text-sm text-fg-2">{result}</span>}
          </div>
        </div>
      )}
    </>
  );
}
