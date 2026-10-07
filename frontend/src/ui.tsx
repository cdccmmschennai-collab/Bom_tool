import type { User } from "./types";

export function initials(user: User) {
  const words = (user.full_name || user.username).trim().split(/\s+/);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? words[words.length - 1][0] : words[0]?.[1] ?? "")).toUpperCase();
}

/* ------------------------------------------------------------------ icons */
const svg = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export function UploadIcon() {
  return <svg {...svg}><path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 8.5a4 4 0 0 1-.5 9.5" /><path d="M12 12v8M8.5 15.5 12 12l3.5 3.5" /></svg>;
}
export function LayersIcon() {
  return <svg {...svg}><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 13 9 5 9-5" /></svg>;
}
export function ClockIcon() {
  return <svg {...svg}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>;
}
export function BoxIcon() {
  return <svg {...svg}><path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" /><path d="m3 8 9 5 9-5M12 13v8" /></svg>;
}
export function GearIcon() {
  return <svg {...svg}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></svg>;
}
export function UserIcon() {
  return <svg {...svg}><circle cx="12" cy="8" r="4" /><path d="M4 20.5c1.4-3.6 4.4-5.5 8-5.5s6.6 1.9 8 5.5" /></svg>;
}
export function LockIcon() {
  return <svg {...svg}><rect x="4.5" y="10.5" width="15" height="10" rx="2" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" /></svg>;
}
export function SlidersIcon() {
  return <svg {...svg}><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></svg>;
}

export function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
      {!open && <path d="M3 3l18 18" />}
    </svg>
  );
}

export function SearchIcon() {
  return <svg {...svg}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></svg>;
}
export function DownloadIcon() {
  return <svg {...svg} width={15} height={15}><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14" /></svg>;
}
export function TrashIcon() {
  return <svg {...svg} width={15} height={15}><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5M10.5 11v5M13.5 11v5" /></svg>;
}
export function CombineIcon() {
  return <svg {...svg} width={15} height={15}><path d="M6 4v5a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v5M18 4v5a3 3 0 0 1-3 3M15.5 17.5 18 20l2.5-2.5" /></svg>;
}
export function ChevronIcon({ dir }: { dir: "left" | "right" }) {
  return <svg {...svg} width={16} height={16}><path d={dir === "left" ? "m14.5 6-6 6 6 6" : "m9.5 6 6 6-6 6"} /></svg>;
}
