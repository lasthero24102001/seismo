import { Download, FileSpreadsheet } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorBox, InfoBox, PageHeader, Spinner } from "@/components/common";
import { EventsTable } from "@/components/EventsTable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { api, type SeismicEvent, type Station } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

interface Report {
  title: string; period: { year: number | null; date_from: string; date_to: string }; generated_at: string; total: number; truncated: boolean;
  stations: { code: string; name: string | null; count: number }[]; events: SeismicEvent[]; message: string | null;
}

export default function Reports() {
  const year0 = new Date().getFullYear();
  const [year, setYear] = useState(String(year0));
  const [from, setFrom] = useState(`${year0}-01-01`); const [to, setTo] = useState(`${year0}-12-31`);
  const [sel, setSel] = useState<string[]>([]);
  const [layout, setLayout] = useState<"single" | "split">("single");
  const [rep, setRep] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const stations = useAsync(() => api.get<Station[]>("/stations"), []);

  useEffect(() => { if (/^\d{4}$/.test(year)) { setFrom(`${year}-01-01`); setTo(`${year}-12-31`); } }, [year]);
  const params = { year: /^\d{4}$/.test(year) ? year : "", date_from: from, date_to: to, stations: sel.join(",") };
  const toggle = (c: string) => setSel(sel.includes(c) ? sel.filter((x) => x !== c) : [...sel, c]);

  async function build() {
    setBusy(true); setErr(null);
    try { setRep(await api.get<Report>("/reports", params)); } catch (e) { setErr((e as Error).message); setRep(null); } finally { setBusy(false); }
  }
  async function download() {
    setErr(null);
    try { await api.download("/reports/export.xlsx", params, "report.xlsx"); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <>
      <PageHeader title="Отчёты" subtitle="Отчёт формируется из PostgreSQL за выбранный период; значения выводятся как в бюллетенях, без пересчёта" />
      <Card className="mb-4 p-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div><Label>Год</Label><Input type="number" value={year} onChange={(e) => setYear(e.target.value)} /></div>
          <div><Label>Начальная дата</Label><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
          <div><Label>Конечная дата</Label><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
          <div><Label>Вид отчёта</Label>
            <div className="flex overflow-hidden rounded-md border">{([["single", "Единая таблица"], ["split", "По станциям"]] as const).map(([k, l]) => <button key={k} onClick={() => setLayout(k)} className={`flex-1 px-2 py-2 text-xs font-medium ${layout === k ? "bg-primary text-white" : "bg-white"}`}>{l}</button>)}</div></div>
        </div>
        <div className="mt-3"><Label>Станции {sel.length === 0 && "(выбраны все)"}</Label>
          <div className="flex flex-wrap gap-1.5">{stations.data?.map((s) => <button key={s.code} onClick={() => toggle(s.code)} className={`rounded-full border px-3 py-1 text-xs font-medium ${sel.includes(s.code) ? "border-primary bg-primary text-white" : "bg-white hover:bg-muted"}`}>{s.code}</button>)}
            {sel.length > 0 && <button className="px-2 text-xs text-muted-foreground underline" onClick={() => setSel([])}>все станции</button>}</div></div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={build} disabled={busy}>{busy ? <Spinner /> : <FileSpreadsheet className="h-4 w-4" />} Сформировать отчёт</Button>
          <Button variant="outline" onClick={download}><Download className="h-4 w-4" /> Скачать Excel</Button>
        </div>
      </Card>
      <ErrorBox message={err} />
      {rep && (
        <>
          <Card className="mb-4 p-5">
            <h2 className="text-base font-semibold">{rep.title}</h2>
            <div className="mt-1 text-sm text-muted-foreground">Период: {fmtDate(rep.period.date_from)} – {fmtDate(rep.period.date_to)} · Сформирован: {fmtDateTime(rep.generated_at)} · Событий: <b className="text-foreground">{rep.total.toLocaleString("ru-RU")}</b></div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">{rep.stations.map((s) => <span key={s.code} className="rounded-md border bg-muted px-2 py-1"><b>{s.code}</b>{s.name ? ` · ${s.name}` : ""}: {s.count}</span>)}</div>
          </Card>
          {rep.message && <InfoBox tone="warn">{rep.message}. Проверьте период и выбранные станции — например, импортированные данные могут относиться к другому году.</InfoBox>}
          {rep.truncated && <InfoBox tone="warn">В предпросмотре показаны первые {rep.events.length.toLocaleString("ru-RU")} записей из {rep.total.toLocaleString("ru-RU")}. Файл Excel содержит все записи.</InfoBox>}
          {rep.total > 0 && (layout === "single" ? <EventsTable events={rep.events} /> : rep.stations.map((s) => {
            const ev = rep.events.filter((e) => e.station_code === s.code);
            return <div key={s.code} className="mb-6"><h3 className="mb-2 text-sm font-semibold">{s.code}{s.name ? ` — ${s.name}` : ""} <span className="font-normal text-muted-foreground">({s.count})</span></h3>
              {ev.length ? <EventsTable events={ev} hideStation /> : <div className="rounded-md border bg-white p-4 text-sm text-muted-foreground">Нет данных за период</div>}</div>;
          }))}
        </>
      )}
    </>
  );
}
