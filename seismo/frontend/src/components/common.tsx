import { AlertTriangle, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { reasonText } from "@/lib/format";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

export const PageHeader = ({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) => (
  <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
    </div>
    <div className="flex flex-wrap gap-2">{actions}</div>
  </div>
);

export const ErrorBox = ({ message }: { message: string | null }) =>
  message ? (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{message}</span>
    </div>
  ) : null;

export const InfoBox = ({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) => (
  <div className={`mb-4 rounded-md border px-3 py-2 text-sm ${tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-blue-200 bg-blue-50 text-blue-900"}`}>{children}</div>
);

export const Spinner = () => <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;

export const StatCard = ({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "warn" }) => (
  <Card className="p-4">
    <div className="text-xs font-medium text-muted-foreground">{label}</div>
    <div className={`mt-1 text-2xl font-semibold ${tone === "warn" ? "text-amber-600" : ""}`}>{value}</div>
    {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
  </Card>
);

export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
      <span>{from}–{Math.min(page * pageSize, total)} из {total.toLocaleString("ru-RU")}</span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Назад"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="px-2">стр. {page} / {pages}</span>
        <Button variant="outline" size="icon" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Вперёд"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

export const ReasonBadges = ({ reasons }: { reasons: string[] }) => (
  <div className="flex flex-col gap-1">
    {reasons.map((r) => <Badge key={r} variant="warn" className="w-fit whitespace-normal">{reasonText(r)}</Badge>)}
  </div>
);
