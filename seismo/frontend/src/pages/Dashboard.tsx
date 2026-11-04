import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ErrorBox, InfoBox, PageHeader, Spinner, StatCard } from "@/components/common";
import { EventsTable } from "@/components/EventsTable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type SeismicEvent } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

interface Dash {
  totals: { events: number; stations_with_data: number; stations_total: number; events_month: number; events_year: number; flagged: number; today: string; first_date: string | null; last_date: string | null; events_in_period: number };
  period: { date_from: string | null; date_to: string | null }; exclude_flagged: boolean;
  by_month: { month: string; count: number }[]; by_station: { station: string; count: number }[]; daily: { date: string; count: number }[];
  magnitude: { date: string; mb_avg: number | null; ml_avg: number | null; mb_max: number | null; ml_max: number | null; n: number }[];
  recent_imports: { file: string; station: string | null; rows_imported: number; rows_duplicate: number; rows_flagged: number; imported_at: string | null }[];
  recent_events: SeismicEvent[];
}

const BLUE = "#2563eb", SKY = "#38bdf8", AMBER = "#f59e0b";
const ChartCard = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><div className="h-64">{children}</div></CardContent></Card>
);

export default function Dashboard() {
  const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [excl, setExcl] = useState(true);
  const { data: d, error, loading } = useAsync(() => api.get<Dash>("/dashboard", { date_from: from, date_to: to, exclude_flagged: excl }), [from, to, excl]);
  if (!d) return <>{error ? <ErrorBox message={error} /> : <Spinner />}</>;
  const t = d.totals;
  return (
    <>
      <PageHeader title="Dashboard" subtitle={t.first_date ? `Данные в базе: ${fmtDate(t.first_date)} – ${fmtDate(t.last_date)}` : "База пуста — загрузите бюллетени в разделе «Импорт данных»"} actions={loading ? <Spinner /> : null} />
      <ErrorBox message={error} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Всего событий" value={t.events.toLocaleString("ru-RU")} />
        <StatCard label="Станций с данными" value={`${t.stations_with_data} / ${t.stations_total}`} />
        <StatCard label="За текущий месяц" value={t.events_month} hint={`на ${fmtDate(t.today)}`} />
        <StatCard label="За текущий год" value={t.events_year.toLocaleString("ru-RU")} />
        <StatCard label="За выбранный период" value={t.events_in_period.toLocaleString("ru-RU")} />
        <StatCard label="Требуют проверки" value={t.flagged} tone={t.flagged ? "warn" : undefined} />
      </div>
      {t.events > 0 && t.events_month === 0 && <div className="mt-3"><InfoBox>В текущем месяце событий нет. Последние данные в базе — за {fmtDate(t.last_date)}.</InfoBox></div>}

      <Card className="mt-4 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div><Label>Период с</Label><Input type="date" value={from || d.period.date_from || ""} onChange={(e) => setFrom(e.target.value)} /></div>
          <div><Label>по</Label><Input type="date" value={to || d.period.date_to || ""} onChange={(e) => setTo(e.target.value)} /></div>
          <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={excl} onChange={(e) => setExcl(e.target.checked)} /> Не учитывать помеченные записи в графике магнитуд</label>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ChartCard title="События по месяцам (вся база)">
          <ResponsiveContainer><BarChart data={d.by_month}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="month" fontSize={12} /><YAxis fontSize={12} /><Tooltip /><Bar dataKey="count" name="Событий" fill={BLUE} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Распределение по станциям (выбранный период)">
          <ResponsiveContainer><BarChart data={d.by_station} layout="vertical"><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" fontSize={12} /><YAxis type="category" dataKey="station" fontSize={12} width={50} /><Tooltip /><Bar dataKey="count" name="Событий" fill={SKY} radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title={`Динамика магнитуд Mb и ML (среднее за день${d.exclude_flagged ? ", без помеченных" : ""})`}>
          <ResponsiveContainer><LineChart data={d.magnitude.map((m) => ({ ...m, date: fmtDate(m.date).slice(0, 5) }))}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" fontSize={12} /><YAxis fontSize={12} /><Tooltip /><Legend /><Line type="monotone" dataKey="mb_avg" name="Mb (ср.)" stroke={BLUE} dot={false} strokeWidth={2} /><Line type="monotone" dataKey="ml_avg" name="ML (ср.)" stroke={AMBER} dot={false} strokeWidth={2} /></LineChart></ResponsiveContainer>
        </ChartCard>
        <ChartCard title="События по дням (выбранный период)">
          <ResponsiveContainer><BarChart data={d.daily.map((x) => ({ ...x, date: fmtDate(x.date).slice(0, 5) }))}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" fontSize={12} /><YAxis fontSize={12} /><Tooltip /><Bar dataKey="count" name="Событий" fill={BLUE} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>
        </ChartCard>
      </div>

      <h2 className="mb-2 mt-6 text-sm font-semibold">Последние импортированные файлы</h2>
      <Table><THead><TR><TH>Файл</TH><TH>Станция</TH><TH>Импортировано</TH><TH>Дубликатов</TH><TH>Помечено</TH><TH>Когда</TH></TR></THead>
        <TBody>{d.recent_imports.map((f, i) => <TR key={i}><TD>{f.file}</TD><TD>{f.station}</TD><TD>{f.rows_imported}</TD><TD>{f.rows_duplicate}</TD><TD>{f.rows_flagged}</TD><TD>{fmtDateTime(f.imported_at)}</TD></TR>)}
          {!d.recent_imports.length && <TR><TD colSpan={6} className="text-muted-foreground">Импортов ещё не было</TD></TR>}</TBody></Table>
      <h2 className="mb-2 mt-6 text-sm font-semibold">Последние зарегистрированные события</h2>
      <EventsTable events={d.recent_events} />
    </>
  );
}
