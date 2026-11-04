import { DatabaseBackup, Download } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox, InfoBox, PageHeader, Pagination, Spinner } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, fmtSize } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

export default function SettingsPage() {
  const { user, isAdmin, logout } = useAuth();
  const [old, setOld] = useState(""); const [nw, setNw] = useState(""); const [msg, setMsg] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null);

  async function change(e: FormEvent) {
    e.preventDefault(); setErr(null); setMsg(null);
    try { await api.post("/auth/change-password", { old_password: old, new_password: nw }); setMsg("Пароль изменён. Выполните вход заново."); setTimeout(logout, 1500); } catch (x) { setErr((x as Error).message); }
  }
  return (
    <>
      <PageHeader title="Настройки" subtitle={`Учётная запись: ${user?.username}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Смена пароля</CardTitle></CardHeader><CardContent>
          <ErrorBox message={err} />{msg && <InfoBox>{msg}</InfoBox>}
          <form onSubmit={change} className="space-y-3">
            <div><Label>Текущий пароль</Label><Input type="password" value={old} onChange={(e) => setOld(e.target.value)} required autoComplete="current-password" /></div>
            <div><Label>Новый пароль (не менее 8 символов)</Label><Input type="password" minLength={8} value={nw} onChange={(e) => setNw(e.target.value)} required autoComplete="new-password" /></div>
            <Button>Изменить пароль</Button>
          </form></CardContent></Card>
        {isAdmin && <Backups />}
      </div>
      {isAdmin && <Audit />}
    </>
  );
}

function Backups() {
  const { data, error, reload } = useAsync(() => api.get<{ name: string; size: number; created_at: string }[]>("/admin/backups"), []);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  async function create() { setBusy(true); setErr(null); try { await api.post("/admin/backups"); reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); } }
  return (
    <Card><CardHeader><CardTitle>Резервное копирование БД</CardTitle></CardHeader><CardContent>
      <ErrorBox message={error || err} />
      <Button onClick={create} disabled={busy}>{busy ? <Spinner /> : <DatabaseBackup className="h-4 w-4" />} Создать копию (pg_dump)</Button>
      <ul className="mt-3 divide-y text-sm">{data?.map((b) => <li key={b.name} className="flex items-center justify-between py-2"><span>{b.name} <span className="text-xs text-muted-foreground">{fmtSize(b.size)} · {fmtDateTime(b.created_at)}</span></span>
        <Button variant="ghost" size="icon" onClick={() => api.download(`/admin/backups/${b.name}`, undefined, b.name)}><Download className="h-4 w-4" /></Button></li>)}
        {data && !data.length && <li className="py-2 text-muted-foreground">Копий пока нет</li>}</ul>
      <p className="mt-3 text-xs text-muted-foreground">Восстановление: <code>docker compose exec -T db pg_restore -U seismo -d seismo --clean &lt; backups/файл.dump</code></p>
    </CardContent></Card>
  );
}

function Audit() {
  const [page, setPage] = useState(1);
  const { data } = useAsync(() => api.get<{ total: number; items: { id: number; created_at: string; username: string | null; action: string; entity_type: string | null; entity_id: string | null; details: unknown; ip: string | null }[] }>("/admin/audit", { page, page_size: 20 }), [page]);
  return (
    <>
      <h2 className="mb-2 mt-8 text-sm font-semibold">Журнал действий пользователей</h2>
      {data && <><Table><THead><TR><TH>Время</TH><TH>Пользователь</TH><TH>Действие</TH><TH>Объект</TH><TH>Детали</TH><TH>IP</TH></TR></THead>
        <TBody>{data.items.map((a) => <TR key={a.id}><TD>{fmtDateTime(a.created_at)}</TD><TD>{a.username ?? "—"}</TD><TD>{a.action}</TD><TD>{a.entity_type ? `${a.entity_type} #${a.entity_id ?? ""}` : "—"}</TD>
          <TD className="max-w-md truncate text-xs text-muted-foreground" title={JSON.stringify(a.details)}>{a.details ? JSON.stringify(a.details) : ""}</TD><TD>{a.ip}</TD></TR>)}</TBody></Table>
        <Pagination page={page} pageSize={20} total={data.total} onChange={setPage} /></>}
    </>
  );
}
