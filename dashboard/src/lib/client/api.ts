"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: Array<{ path: string; message: string }>) {
    super(message);
  }
}

export async function apiFetch<T = unknown>(url: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  const response = await fetch(url, {
    method: init.method ?? (init.body === undefined ? "GET" : "POST"),
    headers: init.body === undefined || isForm ? undefined : { "content-type": "application/json" },
    body: init.body === undefined ? undefined : isForm ? (init.body as FormData) : JSON.stringify(init.body),
    credentials: "same-origin",
    cache: "no-store",
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const details = Array.isArray(data?.details) ? data.details : undefined;
    const suffix = details?.length ? `: ${details.map((d: { path: string; message: string }) => `${d.path} ${d.message}`).join(", ")}` : "";
    throw new ApiError(response.status, `${data?.error || "Solicitud fallida"}${suffix}`, details);
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Ocurrió un error inesperado";
}

/** Minimal data hook: loads ``url`` (null = skip), exposes reload and local mutation. */
export function useApi<T>(url: string | null) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(url));
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!url) return;
    const id = ++seq.current;
    setLoading(true);
    try {
      const result = await apiFetch<T>(url);
      if (id === seq.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (id === seq.current) setError(errorMessage(err));
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}
