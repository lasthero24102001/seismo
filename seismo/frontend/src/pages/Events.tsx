import { Download } from "lucide-react";
import { useState } from "react";
import { ErrorBox, PageHeader, Pagination, Spinner } from "@/components/common";
import EventDialog from "@/components/EventDialog";
import { EventsTable } from "@/components/EventsTable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { api, type Page, type SeismicEvent, type Station } from "@/lib/api";
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
