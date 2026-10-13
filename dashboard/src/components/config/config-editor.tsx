"use client";

import { RotateCcw, Save } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ColorInput, Field, Input, NumberInput, Select, TagInput, Textarea, Toggle } from "@/components/ui/form";
import { Spinner } from "@/components/ui/misc";
import { type ChannelKind, ChannelMultiPicker, ChannelPicker, RoleMultiPicker, RolePicker } from "@/components/ui/pickers";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "@/lib/client/api";
import { useGuild } from "@/lib/client/guild";
import { CONFIG_EVENT } from "@/lib/client/events";

export type Config = Record<string, unknown>;

interface Base { key: string; label?: string; help?: React.ReactNode; wide?: boolean; showIf?: (config: Config) => boolean }

/** Declarative description of one GuildConfig field. */
export type FieldSpec = Base & (
  | { type: "toggle"; description?: string }
  | { type: "text"; placeholder?: string; max?: number; mono?: boolean }
  | { type: "textarea"; placeholder?: string; max?: number; rows?: number; vars?: string[] }
  | { type: "number"; min?: number; max?: number; step?: number; suffix?: string }
  | { type: "color" }
  | { type: "channel"; kind?: ChannelKind; placeholder?: string }
  | { type: "channels"; kind?: ChannelKind }
  | { type: "role"; assignableOnly?: boolean; placeholder?: string }
  | { type: "roles"; assignableOnly?: boolean }
  | { type: "select"; options: Array<{ value: string; label: string }> }
  | { type: "tags"; placeholder?: string }
  | { type: "custom"; render: (value: unknown, set: (value: unknown) => void, config: Config) => React.ReactNode }
);

export interface SectionSpec {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  fields: FieldSpec[];
}

interface ConfigContextValue {
  config: Config;
  set: (key: string, value: unknown) => void;
  saved: Config;
}
const ConfigContext = createContext<ConfigContextValue | null>(null);

/** Access the editor's draft from custom blocks rendered inside ``<ConfigEditor>``. */
export function useConfigDraft(): ConfigContextValue {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error("useConfigDraft must be used inside ConfigEditor");
  return ctx;
}

function FieldControl({ spec, value, set, config }: { spec: FieldSpec; value: unknown; set: (v: unknown) => void; config: Config }) {
  const id = `cfg-${spec.key}`;
  switch (spec.type) {
    case "toggle":
      return <Toggle checked={Boolean(value)} onChange={set} label={spec.label} description={spec.description} />;
    case "text":
      return <Input id={id} value={(value as string) ?? ""} placeholder={spec.placeholder} maxLength={spec.max}
                    className={spec.mono ? "font-mono" : undefined} onChange={(e) => set(e.target.value)} />;
    case "textarea":
      return (
        <>
          <Textarea id={id} value={(value as string) ?? ""} placeholder={spec.placeholder} maxLength={spec.max}
                    rows={spec.rows ?? 4} onChange={(e) => set(e.target.value)} />
          {spec.vars && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {spec.vars.map((v) => (
                <button key={v} type="button" className="kbd hover:border-line-strong hover:text-fg"
                        onClick={() => set(`${(value as string) ?? ""}${v}`)}>{v}</button>
              ))}
            </div>
          )}
        </>
      );
    case "number":
      return <NumberInput id={id} value={value as number} min={spec.min} max={spec.max} step={spec.step} suffix={spec.suffix} onChange={set} />;
    case "color":
      return <ColorInput value={value as string} onChange={set} />;
    case "channel":
      return <ChannelPicker id={id} value={value as string} kind={spec.kind} placeholder={spec.placeholder} onChange={set} />;
    case "channels":
      return <ChannelMultiPicker value={(value as string[]) ?? []} kind={spec.kind} onChange={set} />;
    case "role":
      return <RolePicker id={id} value={value as string} assignableOnly={spec.assignableOnly} placeholder={spec.placeholder} onChange={set} />;
    case "roles":
      return <RoleMultiPicker value={(value as string[]) ?? []} assignableOnly={spec.assignableOnly} onChange={set} />;
    case "select":
      return <Select id={id} value={(value as string) ?? ""} options={spec.options} onChange={set} />;
    case "tags":
      return <TagInput value={(value as string[]) ?? []} placeholder={spec.placeholder} onChange={set} />;
    case "custom":
      return <>{spec.render(value, set, config)}</>;
  }
}

function changedKeys(draft: Config, saved: Config): string[] {
  return Object.keys(draft).filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(saved[k]));
}

/**
 * Loads the guild config, renders sections of fields, and saves only the
 * changed keys with PATCH. Children can use ``useConfigDraft()`` for custom blocks.
 */
export function ConfigEditor({ sections, children, header }: {
  sections: SectionSpec[]; children?: React.ReactNode; header?: React.ReactNode;
}) {
  const { api } = useGuild();
  const { data, error, loading, setData } = useApi<Config>(`${api}/config`);
  const [draft, setDraft] = useState<Config>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);

  const set = useCallback((key: string, value: unknown) => setDraft((d) => ({ ...d, [key]: value })), []);
  const dirty = useMemo(() => (data ? changedKeys(draft, data) : []), [draft, data]);

  const save = async () => {
    if (!data || !dirty.length) return;
    setSaving(true);
    try {
      const patch = Object.fromEntries(dirty.map((k) => [k, draft[k]]));
      const updated = await apiFetch<Config>(`${api}/config`, { method: "PATCH", body: patch });
      setData(updated);
      setDraft(updated);
      window.dispatchEvent(new CustomEvent(CONFIG_EVENT, { detail: updated }));
      toast.success("Cambios guardados");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) return <Spinner />;
  if (error && !data) return <Card><CardBody><p className="text-sm text-muted">{error}</p></CardBody></Card>;

  return (
    <ConfigContext.Provider value={{ config: draft, set, saved: data ?? {} }}>
      <div className="space-y-5 pb-24">
        {header}
        {sections.map((section) => {
          const visible = section.fields.filter((f) => !f.showIf || f.showIf(draft));
          if (!visible.length) return null;
          return (
            <Card key={section.title}>
              <CardHeader title={section.title} description={section.description} icon={section.icon} />
              <CardBody className="grid gap-5 md:grid-cols-2">
                {visible.map((spec) => (
                  <div key={spec.key} className={spec.type === "toggle" || spec.wide || spec.type === "textarea" ? "md:col-span-2" : undefined}>
                    {spec.type === "toggle" ? (
                      <><FieldControl spec={spec} value={draft[spec.key]} set={(v) => set(spec.key, v)} config={draft} />
                        {spec.help && <p className="help">{spec.help}</p>}</>
                    ) : (
                      <Field label={spec.label} help={spec.help} htmlFor={`cfg-${spec.key}`}>
                        <FieldControl spec={spec} value={draft[spec.key]} set={(v) => set(spec.key, v)} config={draft} />
                      </Field>
                    )}
                  </div>
                ))}
              </CardBody>
            </Card>
          );
        })}
        {children}
      </div>
      {dirty.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line-strong bg-surface/95 backdrop-blur lg:left-64">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3">
            <span className="text-sm text-fg-2">{dirty.length} cambio{dirty.length === 1 ? "" : "s"} sin guardar</span>
            <div className="flex gap-2">
              <Button variant="ghost" icon={<RotateCcw size={14} />} onClick={() => setDraft(data ?? {})}>Descartar</Button>
              <Button variant="primary" icon={<Save size={14} />} loading={saving} onClick={save}>Guardar</Button>
            </div>
          </div>
        </div>
      )}
    </ConfigContext.Provider>
  );
}
