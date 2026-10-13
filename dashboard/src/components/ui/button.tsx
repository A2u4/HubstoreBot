"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { forwardRef } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-fg text-bg hover:bg-fg-2 border border-fg",
  secondary: "bg-surface-2 text-fg border border-line hover:border-line-strong hover:bg-surface-3",
  ghost: "text-fg-2 hover:bg-surface-3 hover:text-fg border border-transparent",
  danger: "bg-transparent text-fg border border-line-strong hover:bg-fg hover:text-bg",
};
const SIZES: Record<Size, string> = { sm: "h-8 px-3 text-xs gap-1.5", md: "h-9 px-4 text-sm gap-2" };

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, type = "button", ...props }, ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading}
            className={cn("inline-flex shrink-0 items-center justify-center rounded-lg font-medium transition-colors",
                          "disabled:cursor-not-allowed disabled:opacity-50", VARIANTS[variant], SIZES[size], className)}
            {...props}>
      {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      {children}
    </button>
  );
});

export function ButtonLink({ href, variant = "secondary", size = "md", className, children, icon }: {
  href: string; variant?: Variant; size?: Size; className?: string; children: React.ReactNode; icon?: React.ReactNode;
}) {
  return (
    <Link href={href} className={cn("inline-flex items-center justify-center rounded-lg font-medium transition-colors",
                                    VARIANTS[variant], SIZES[size], className)}>
      {icon}
      {children}
    </Link>
  );
}
