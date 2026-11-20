import { ListPlus, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ErrorBox, PageHeader, Spinner } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { InfoBox } from "@/components/common";
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
  const [bulk, setBulk] = useState(false); const [bulkText, setBulkText] = useState("");
  const [bulkRes, setBulkRes] = useState<{ created: string[]; skipped: { code: string; station: string }[]; invalid: string[] } | null>(null);
  const [bulkErr, setBulkErr] = useState<string | null>(null);
  async function addBulk() {
    setBulkErr(null);
    try { setBulkRes(await api.post("/stations/bulk", { codes: bulkText })); reload(); } catch (e) { setBulkErr((e as Error).message); }
  }

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
      <PageHeader title="Сейсмостанции" subtitle="Справочник станций. Новые станции можно добавлять без изменения кода — также создаются автоматически при импорте" actions={canWrite && <>
        <Button variant="outline" onClick={() => { setBulk(true); setBulkText(""); setBulkRes(null); setBulkErr(null); }}><ListPlus className="h-4 w-4" /> Добавить списком</Button>
        <Button onClick={() => open()}><Plus className="h-4 w-4" /> Добавить станцию</Button></>} />
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
      <Dialog open={bulk} onOpenChange={setBulk}>
        <DialogContent title="Добавить станции списком" description="Коды через запятую, пробел или с новой строки. Уже существующие пропускаются.">
          <ErrorBox message={bulkErr} />
          {!bulkRes ? (
            <div className="space-y-3">
              <textarea className="h-32 w-full rounded-md border border-input p-2 font-mono text-sm uppercase focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="SNGR, YANG, TSHT…" value={bulkText} onChange={(e) => setBulkText(e.target.value)} />
              <div className="text-xs text-muted-foreground">Код — латинские буквы и цифры, начинается с буквы, 2–8 символов. Названия можно задать потом в таблице.</div>
              <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setBulk(false)}>Отмена</Button><Button onClick={addBulk} disabled={!bulkText.trim()}>Добавить</Button></div>
            </div>
          ) : (
            <div className="space-y-3 text-sm">
              <InfoBox>Добавлено станций: <b>{bulkRes.created.length}</b>{bulkRes.created.length > 0 && ` — ${bulkRes.created.join(", ")}`}</InfoBox>
              {bulkRes.skipped.length > 0 && <div>Уже были в справочнике ({bulkRes.skipped.length}): {bulkRes.skipped.map((x) => x.code === x.station ? x.code : `${x.code} (алиас ${x.station})`).join(", ")}</div>}
              {bulkRes.invalid.length > 0 && <div className="text-red-700">Некорректные коды, не добавлены: {bulkRes.invalid.join(", ")}</div>}
              <div className="flex justify-end"><Button onClick={() => setBulk(false)}>Готово</Button></div>
            </div>
          )}
        </DialogContent>
      </Dialog>

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
