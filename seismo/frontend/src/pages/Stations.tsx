import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ErrorBox, PageHeader, Spinner } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type Station } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

export default function Stations() {
  const { canWrite, isAdmin } = useAuth();
  const { data, error, reload } = useAsync(() => api.get<Station[]>("/stations"), []);
  const [dlg, setDlg] = useState<Partial<Station> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", aliases: "" });

  const open = (s?: Station) => { setErr(null); setDlg(s ?? {}); setForm({ code: s?.code ?? "", name: s?.name ?? "", aliases: (s?.aliases ?? []).join(", ") }); };
  async function save() {
    setErr(null);
    const aliases = form.aliases.split(",").map((a) => a.trim()).filter(Boolean);
    try {
      if (dlg?.id) await api.patch(`/stations/${dlg.id}`, { name: form.name, aliases });
      else await api.post("/stations", { code: form.code, name: form.name || null, aliases });
      setDlg(null); reload();
    } catch (e) { setErr((e as Error).message); }
  }
  async function toggle(s: Station) { await api.patch(`/stations/${s.id}`, { is_active: !s.is_active }).catch((e) => setErr(e.message)); reload(); }
  async function remove(s: Station) {
    if (!confirm(`Удалить станцию ${s.code}?`)) return;
    try { await api.del(`/stations/${s.id}`); reload(); } catch (e) { alert((e as Error).message); }
  }
  return (
    <>
      <PageHeader title="Сейсмостанции" subtitle="Справочник станций. Новые станции можно добавлять без изменения кода — также создаются автоматически при импорте" actions={canWrite && <Button onClick={() => open()}><Plus className="h-4 w-4" /> Добавить станцию</Button>} />
      <ErrorBox message={error || (dlg ? null : err)} />
      {!data ? <Spinner /> : (
        <Table>
          <THead><TR><TH>Код</TH><TH>Название</TH><TH>Алиасы в данных</TH><TH>Записей</TH><TH>Помечено</TH><TH>Период данных</TH><TH>Статус</TH><TH /></TR></THead>
          <TBody>{data.map((s) => (
            <TR key={s.id}>
              <TD className="font-semibold">{s.code}</TD>
              <TD>{s.name || <span className="text-muted-foreground">не задано</span>}</TD>
              <TD>{s.aliases.join(", ") || "—"}</TD>
              <TD>{s.events_count.toLocaleString("ru-RU")}</TD>
              <TD>{s.flagged_count ? <Badge variant="warn">{s.flagged_count}</Badge> : 0}</TD>
              <TD>{s.first_date ? `${fmtDate(s.first_date)} – ${fmtDate(s.last_date)}` : <span className="text-muted-foreground">нет данных</span>}</TD>
              <TD><Badge variant={s.is_active ? "success" : "muted"}>{s.is_active ? "Активна" : "Отключена"}</Badge></TD>
              <TD className="text-right">{canWrite && <div className="flex justify-end gap-1">
                <Button variant="ghost" size="icon" onClick={() => open(s)} aria-label="Изменить"><Pencil className="h-4 w-4" /></Button>
                <Button variant="ghost" size="sm" onClick={() => toggle(s)}>{s.is_active ? "Отключить" : "Включить"}</Button>
                {isAdmin && <Button variant="ghost" size="icon" onClick={() => remove(s)} aria-label="Удалить"><Trash2 className="h-4 w-4 text-destructive" /></Button>}
              </div>}</TD>
            </TR>))}</TBody>
        </Table>
      )}
      <Dialog open={!!dlg} onOpenChange={(o) => !o && setDlg(null)}>
        <DialogContent title={dlg?.id ? `Станция ${dlg.code}` : "Новая станция"}>
          <ErrorBox message={err} />
          <div className="space-y-3">
            <div><Label>Код (как в бюллетене)</Label><Input value={form.code} disabled={!!dlg?.id} onChange={(e) => setForm({ ...form, code: e.target.value })} /></div>
            <div><Label>Название</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div><Label>Алиасы кода в данных (через запятую, напр. PSKM)</Label><Input value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} /></div>
            <div className="flex justify-end gap-2 pt-2"><Button variant="outline" onClick={() => setDlg(null)}>Отмена</Button><Button onClick={save}>Сохранить</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
