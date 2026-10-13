"use client";

import { useCallback } from "react";
import { confirm } from "@/components/ui/modal";
import { toast } from "@/components/ui/toast";
import { apiFetch, errorMessage, useApi } from "./api";

/** List + create/update/delete against a guild collection route, with toasts and local state updates. */
export function useCollection<T extends { id: string }>(url: string) {
  const { data, loading, error, reload, setData } = useApi<T[]>(url);

  const create = useCallback(async (body: unknown, message = "Creado"): Promise<T | null> => {
    try {
      const row = await apiFetch<T>(url, { body });
      setData((rows) => [...(rows ?? []), row]);
      toast.success(message);
      return row;
    } catch (err) {
      toast.error(errorMessage(err));
      return null;
    }
  }, [url, setData]);

  const update = useCallback(async (id: string, patch: unknown, message: string | null = "Guardado"): Promise<T | null> => {
    try {
      const row = await apiFetch<T>(`${url}/${id}`, { method: "PATCH", body: patch });
      setData((rows) => rows?.map((r) => (r.id === id ? row : r)));
      if (message) toast.success(message);
      return row;
    } catch (err) {
      toast.error(errorMessage(err));
      return null;
    }
  }, [url, setData]);

  const remove = useCallback(async (id: string, question?: string): Promise<boolean> => {
    if (question && !(await confirm({ title: "Eliminar", message: question, confirmLabel: "Eliminar", danger: true }))) return false;
    try {
      await apiFetch(`${url}/${id}`, { method: "DELETE" });
      setData((rows) => rows?.filter((r) => r.id !== id));
      toast.success("Eliminado");
      return true;
    } catch (err) {
      toast.error(errorMessage(err));
      return false;
    }
  }, [url, setData]);

  return { rows: data ?? [], loading, error, reload, create, update, remove, setRows: setData };
}
