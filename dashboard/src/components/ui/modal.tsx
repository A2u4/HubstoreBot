"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button } from "./button";
import { cn } from "./cn";

export function Modal({ open, onClose, title, description, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; description?: string; children: React.ReactNode;
  footer?: React.ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => e.target === ref.current && onClose()}
            className={cn("m-auto max-h-[90vh] w-[calc(100%-2rem)] overflow-hidden rounded-xl border border-line-strong bg-surface p-0 text-fg",
                          "backdrop:bg-black/80 backdrop:backdrop-blur-sm", wide ? "max-w-3xl" : "max-w-lg")}>
      {open && (
        <div className="flex max-h-[90vh] flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <h2 className="text-base font-semibold">{title}</h2>
              {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
            </div>
            <button type="button" onClick={onClose} aria-label="Cerrar" className="text-muted hover:text-fg"><X size={18} /></button>
          </div>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

/** Imperative confirmation dialog: ``if (await confirm({...})) doIt()``. */
export function confirm(options: { title: string; message: string; confirmLabel?: string; danger?: boolean }): Promise<boolean> {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const finish = (value: boolean) => {
      resolve(value);
      setTimeout(() => { root.unmount(); host.remove(); }, 0);
    };
    function Confirm() {
      const [open, setOpen] = useState(true);
      const close = (value: boolean) => { setOpen(false); finish(value); };
      return (
        <Modal open={open} onClose={() => close(false)} title={options.title}
               footer={<>
                 <Button variant="ghost" onClick={() => close(false)}>Cancelar</Button>
                 <Button variant={options.danger ? "danger" : "primary"} onClick={() => close(true)} autoFocus>
                   {options.confirmLabel ?? "Confirmar"}
                 </Button>
               </>}>
          <p className="whitespace-pre-line text-sm leading-relaxed text-fg-2">{options.message}</p>
        </Modal>
      );
    }
    root.render(<Confirm />);
  });
}
