import { Download, Trash2, Pencil, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorBox, PageHeader, Pagination, ReasonBadges, Spinner } from "@/components/common";
import { EventsTable } from "@/components/EventsTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { api, type EventDetail, type Page, type SeismicEvent, type Station } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtDateTime, fmtNum, fmtTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

const EMPTY = { stations: "", q: "", year: "", month: "", date_from: "", date_to: "", mb_min: "", mb_max: "", ml_min: "", ml_max: "", r_min: "", r_max: "", needs_review: "" };
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

export default function Events() {
  const [f, setF] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("date"); const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [openId, setOpenId] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false); const [err, setErr] = useState<string | null>(null);
  const stations = useAsync(() => api.get<Station[]>("/stations"), []);
  const params = { ...f, sort, order, page, page_size: 50 };
  const { data, error, loading, reload } = useAsync(() => api.get<Page<SeismicEvent>>("/events", params), [JSON.stringify(params)]);
  const set = (k: keyof typeof EMPTY, v: string) => { setF({ ...f, [k]: v }); setPage(1); };
  const toggleSort = (k: string) => { if (k === sort) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(k); setOrder("asc"); } setPage(1); };
  const selected = f.stations ? f.stations.split(",") : [];
  const toggleSt = (c: string) => set("stations", (selected.includes(c) ? selected.filter((x) => x !== c) : [...selected, c]).join(","));

  async function exportXlsx() {
    setExporting(true); setErr(null);
    try { const { sort: _s, order: _o, page: _p, page_size: _ps, ...flt } = params; await api.download("/events/export.xlsx", flt, "events.xlsx"); } catch (e) { setErr((e as Error).message); } finally { setExporting(false); }
  }
  return (
    <>
      <PageHeader title="Сейсмологические данные" subtitle="Все импортированные записи бюллетеней" actions={<Button variant="outline" onClick={exportXlsx} disabled={exporting}><Download className="h-4 w-4" /> Excel (с фильтрами)</Button>} />
      <ErrorBox message={error || err} />
      <Card className="mb-4 space-y-3 p-4">
        <div className="flex flex-wrap gap-1.5">
          {stations.data?.map((s) => (
            <button key={s.code} onClick={() => toggleSt(s.code)} className={`rounded-full border px-3 py-1 text-xs font-medium ${selected.includes(s.code) ? "border-primary bg-primary text-white" : "bg-white hover:bg-muted"}`}>{s.code}</button>
          ))}
          {selected.length > 0 && <button className="px-2 text-xs text-muted-foreground underline" onClick={() => set("stations", "")}>все станции</button>}
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
          <div><Label>Поиск по станции</Label><Input value={f.q} onChange={(e) => set("q", e.target.value)} placeholder="код / название" /></div>
          <div><Label>Год</Label><Input type="number" value={f.year} onChange={(e) => set("year", e.target.value)} placeholder="2026" /></div>
          <div><Label>Месяц</Label><Select value={f.month} onChange={(e) => set("month", e.target.value)}><option value="">Все</option>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</Select></div>
          <div><Label>Дата с</Label><Input type="date" value={f.date_from} onChange={(e) => set("date_from", e.target.value)} /></div>
          <div><Label>Дата по</Label><Input type="date" value={f.date_to} onChange={(e) => set("date_to", e.target.value)} /></div>
          <div><Label>Mb от / до</Label><div className="flex gap-1"><Input type="number" step="0.1" value={f.mb_min} onChange={(e) => set("mb_min", e.target.value)} /><Input type="number" step="0.1" value={f.mb_max} onChange={(e) => set("mb_max", e.target.value)} /></div></div>
          <div><Label>ML от / до</Label><div className="flex gap-1"><Input type="number" step="0.1" value={f.ml_min} onChange={(e) => set("ml_min", e.target.value)} /><Input type="number" step="0.1" value={f.ml_max} onChange={(e) => set("ml_max", e.target.value)} /></div></div>
          <div><Label>R км от / до</Label><div className="flex gap-1"><Input type="number" value={f.r_min} onChange={(e) => set("r_min", e.target.value)} /><Input type="number" value={f.r_max} onChange={(e) => set("r_max", e.target.value)} /></div></div>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.needs_review === "true"} onChange={(e) => set("needs_review", e.target.checked ? "true" : "")} /> Только требующие проверки</label>
          <button className="text-xs text-muted-foreground underline" onClick={() => { setF(EMPTY); setPage(1); }}>Сбросить фильтры</button>
          {loading && <Spinner />}
        </div>
      </Card>
      {data && (data.total === 0 ? <Card className="p-8 text-center text-sm text-muted-foreground">Записей по выбранным условиям нет</Card> : (
        <>
          <EventsTable events={data.items} sort={sort} order={order} onSort={toggleSort} onRowClick={(e) => setOpenId(e.id)} />
          <Pagination page={page} pageSize={50} total={data.total} onChange={setPage} />
        </>
      ))}
      <EventDialog id={openId} onClose={() => setOpenId(null)} onChanged={reload} />
    </>
  );
}

const FIELDS: { k: keyof EventDetail; label: string; kind: "text" | "time" | "num" | "date" }[] = [
  { k: "event_date", label: "Дата", kind: "date" }, { k: "p_phase", label: "Фаза P", kind: "text" }, { k: "p_time", label: "Время P", kind: "time" },
  { k: "s_phase", label: "Фаза S", kind: "text" }, { k: "s_time", label: "Время S", kind: "time" }, { k: "origin_time", label: "Время в очаге", kind: "time" },
  { k: "s_minus_p", label: "S-P", kind: "num" }, { k: "r_km", label: "R км", kind: "num" }, { k: "amp_p", label: "A(P) мк/с", kind: "num" }, { k: "amp_s", label: "A(S) мк/с", kind: "num" },
  { k: "mb", label: "Mb", kind: "num" }, { k: "ml", label: "ML", kind: "num" }, { k: "ep_vp", label: "Ep Vp", kind: "num" }, { k: "ep_vs", label: "Ep Vs", kind: "num" }, { k: "ep_vp_vs", label: "Ep Vp/Vs", kind: "num" },
];

function EventDialog({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const { canWrite } = useAuth();
  const [ev, setEv] = useState<EventDetail | null>(null);
  const [edit, setEdit] = useState(false); const [form, setForm] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);

  useEffect(() => {
    setEv(null); setEdit(false); setErr(null);
    if (id) api.get<EventDetail>(`/events/${id}`).then(setEv).catch((e) => setErr(e.message));
  }, [id]);

  function startEdit() {
    if (!ev) return;
    const o: Record<string, string> = { needs_review: String(ev.needs_review), review_comment: ev.review_comment ?? "" };
    FIELDS.forEach(({ k }) => { const v = ev[k]; o[k] = v === null || v === undefined ? "" : String(v); });
    setForm(o); setEdit(true);
  }
  async function save() {
    if (!ev) return;
    setBusy(true); setErr(null);
    try {
      const body: Record<string, unknown> = { needs_review: form.needs_review === "true", review_comment: form.review_comment || null };
      FIELDS.forEach(({ k }) => { body[k] = form[k] === "" ? null : form[k]; });
      setEv(await api.patch<EventDetail>(`/events/${ev.id}`, body)); setEdit(false); onChanged();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!ev || !confirm("Удалить запись безвозвратно? Действие будет записано в журнал.")) return;
    try { await api.del(`/events/${ev.id}`); onClose(); onChanged(); } catch (e) { setErr((e as Error).message); }
  }
  const show = (k: keyof EventDetail, kind: string) => {
    const v = ev![k] as never;
    return kind === "date" ? fmtDate(v) : kind === "time" ? fmtTime(v) : kind === "num" ? fmtNum(v, k === "r_km" || k === "mb" || k === "ml" ? 1 : 2) : (v ?? "—");
  };
  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={ev ? `Запись ${ev.station_code} · ${fmtDate(ev.event_date)} ${fmtTime(ev.p_time)}` : "Запись"} className="max-w-2xl">
        {!ev ? (err ? <ErrorBox message={err} /> : <Spinner />) : (
          <div className="space-y-4">
            <ErrorBox message={err} />
            {ev.needs_review && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><div className="mb-2 text-xs font-semibold text-amber-900">Требует проверки</div><ReasonBadges reasons={ev.review_reasons} /></div>}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {FIELDS.map(({ k, label, kind }) => (
                <div key={k}><Label>{label}</Label>
                  {edit ? <Input value={form[k]} type={kind === "date" ? "date" : "text"} onChange={(e) => setForm({ ...form, [k]: e.target.value })} placeholder={kind === "time" ? "чч:мм:сс,т" : ""} /> : <div className="text-sm font-medium">{show(k, kind) as string}</div>}
                </div>
              ))}
            </div>
            {edit ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div><Label>Статус проверки</Label><Select value={form.needs_review} onChange={(e) => setForm({ ...form, needs_review: e.target.value })}><option value="true">Требует проверки</option><option value="false">Проверено</option></Select></div>
                <div><Label>Комментарий</Label><Input value={form.review_comment} onChange={(e) => setForm({ ...form, review_comment: e.target.value })} /></div>
              </div>
            ) : ev.review_comment && <div className="text-sm"><span className="text-muted-foreground">Комментарий: </span>{ev.review_comment}</div>}
            <div className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              <div>Источник: {ev.file_name ?? "—"}{ev.source_sheet ? `, лист «${ev.source_sheet}»` : ""}{ev.source_row ? `, строка ${ev.source_row}` : ""}{ev.source_no ? `, № ${ev.source_no}` : ""} · импорт {fmtDateTime(ev.created_at)}{ev.updated_at && ` · изменено ${fmtDateTime(ev.updated_at)}`}</div>
              {ev.raw && <div className="overflow-x-auto rounded bg-muted p-2 font-mono text-[11px]">Исходная строка: {JSON.stringify(ev.raw)}</div>}
            </div>
            {canWrite && (
              <div className="flex justify-between">
                <Button variant="destructive" size="sm" onClick={remove}><Trash2 className="h-4 w-4" /> Удалить</Button>
                {edit ? <div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => setEdit(false)}>Отмена</Button><Button size="sm" onClick={save} disabled={busy}><Save className="h-4 w-4" /> Сохранить</Button></div>
                  : <Button variant="outline" size="sm" onClick={startEdit}><Pencil className="h-4 w-4" /> Редактировать</Button>}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
