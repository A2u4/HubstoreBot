import type { MemberInfo } from "@/lib/client/members";

export function Member({ id, info }: { id: string; info?: MemberInfo }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {info ? <img src={info.avatar} alt="" className="size-6 rounded-full grayscale" /> : <span className="size-6 rounded-full bg-surface-3" />}
      <span className="truncate">{info?.displayName ?? <span className="font-mono text-xs text-muted">{id}</span>}</span>
    </span>
  );
}
