"use client";

import { Settings } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { Field } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { RoleMultiPicker } from "@/components/ui/pickers";
import { MODULES } from "@/lib/modules";

const groups = [...new Set(MODULES.map((m) => m.group))];

const sections: SectionSpec[] = [
  {
    title: "Ajustes del bot",
    fields: [
      { key: "prefix", type: "text", label: "Prefijo de comandos de texto", max: 5, mono: true },
      { key: "language", type: "select", label: "Idioma", options: [
        { value: "es", label: "Español" }, { value: "en", label: "English" }, { value: "pt", label: "Português" },
        { value: "fr", label: "Français" }, { value: "de", label: "Deutsch" }] },
      { key: "muteRoleId", type: "role", label: "Rol de silencio", help: "Opcional: se usa además del aislamiento de Discord." },
    ],
  },
  ...groups.map((group): SectionSpec => ({
    title: `Módulos · ${group}`,
    description: "Un módulo desactivado rechaza sus comandos con un aviso.",
    fields: MODULES.filter((m) => m.group === group).map((m) => ({ key: m.toggle, type: "toggle" as const, label: m.label, description: m.description })),
  })),
  {
    title: "Roles por módulo",
    description: "Limita quién puede usar los comandos de staff de cada módulo. Vacío = cualquiera con los permisos de Discord del comando. Los comandos públicos (/perfil, /rep...) no se ven afectados.",
    fields: [{
      key: "moduleAllowedRoles", type: "custom", wide: true,
      render: (value, set) => {
        const map = (value as Record<string, string[]>) ?? {};
        return (
          <div className="grid gap-4 md:grid-cols-2">
            {MODULES.filter((m) => m.name !== "farewell" && m.name !== "welcome").map((m) => (
              <Field key={m.name} label={m.label}>
                <RoleMultiPicker value={map[m.name] ?? []} onChange={(roles) => {
                  const next = { ...map, [m.name]: roles };
                  if (!roles.length) delete next[m.name];
                  set(next);
                }} />
              </Field>
            ))}
          </div>
        );
      },
    }],
  },
];

export default function ConfigPage() {
  return (
    <>
      <PageHeader title="Configuración" description="Módulos y ajustes generales del bot" icon={<Settings size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
