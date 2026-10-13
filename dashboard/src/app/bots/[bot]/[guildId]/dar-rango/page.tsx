"use client";

import { Medal } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { ListEditor, newId } from "@/components/config/list-editor";
import { Field, Input, Textarea } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";

interface RolePattern { id: string; pattern: string; emoji?: string; message?: string }

const DEFAULT_MESSAGE = "¡Felicidades! 🎉\n\nSe te ha asignado el rango **{rol}**.\n\nDisfruta de tus nuevos privilegios.";

const sections: SectionSpec[] = [
  { title: "Archivo de imágenes", fields: [
    { key: "darRangoImagesChannelId", type: "channel", label: "Canal de imágenes",
      help: "/dar-rango vuelve a subir aquí las imágenes del ticket con el ID del usuario (si está vacío usa el canal de verificación)." },
  ] },
  { title: "Mensajes por rango", description: "Si el nombre del rol contiene el patrón, el usuario recibe ese mensaje por DM. Sin coincidencia: Access, VIP o el mensaje genérico. Usa {rol} para el nombre del rol.", fields: [{
    key: "darRangoRoles", type: "custom", wide: true,
    render: (value, set) => (
      <ListEditor<RolePattern>
        value={value as RolePattern[]} onChange={set} addLabel="Añadir patrón" empty="Sin patrones: se usan los mensajes por defecto."
        create={() => ({ id: newId(), pattern: "", emoji: "🎖️", message: DEFAULT_MESSAGE })}
        renderItem={(item, update) => (
          <div className="grid gap-3 md:grid-cols-[1fr_96px]">
            <Field label="El nombre del rol contiene"><Input value={item.pattern} maxLength={100} placeholder="vip" onChange={(e) => update({ pattern: e.target.value })} /></Field>
            <Field label="Emoji"><Input value={item.emoji ?? ""} maxLength={32} onChange={(e) => update({ emoji: e.target.value })} /></Field>
            <Field label="Mensaje" className="md:col-span-2"><Textarea value={item.message ?? ""} maxLength={1000} rows={4} onChange={(e) => update({ message: e.target.value })} /></Field>
          </div>
        )}
      />
    ),
  }] },
];

export default function DarRangoPage() {
  return (
    <>
      <PageHeader title="Dar rango" description="Mensajes de /dar-rango y archivo de comprobantes. El contador de ventas está en /dinero-rangos." icon={<Medal size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
