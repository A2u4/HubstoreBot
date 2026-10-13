"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";

export function UserMenu({ session }: { session: { username: string; id: string; avatar: string | null } }) {
  const router = useRouter();
  const avatar = session.avatar
    ? `https://cdn.discordapp.com/avatars/${session.id}/${session.avatar}.png?size=64`
    : "https://cdn.discordapp.com/embed/avatars/0.png";
  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/");
    router.refresh();
  };
  return (
    <div className="flex items-center gap-2">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={avatar} alt="" className="size-7 rounded-full grayscale" />
      <span className="max-w-32 truncate text-sm text-fg-2">{session.username}</span>
      <button type="button" onClick={logout} title="Cerrar sesión" aria-label="Cerrar sesión"
              className="rounded-md p-1.5 text-muted hover:bg-surface-3 hover:text-fg"><LogOut size={15} /></button>
    </div>
  );
}
