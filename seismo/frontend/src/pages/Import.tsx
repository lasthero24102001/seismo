import { CheckCircle2, FileUp, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { ErrorBox, InfoBox, PageHeader, ReasonBadges, Spinner, StatCard } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Input, Select } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type Station } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtDateTime, fmtNum, fmtSize, fmtTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

interface PreviewRow { source_row: number; sheet: string | null; source_no: number | null; status: string; flags: string[]; error: string | null; station: string; event_date: string | null; p_phase: string | null; p_time: string | null; s_time: string | null; origin_time: string | null; s_minus_p: string | null; r_km: string | null; mb: string | null; ml: string | null; ep_vp_vs: string | null }
interface FileInfo { id: number; original_name: string; file_type: string; size_bytes: number; station_code: string | null; station_hint: string | null; station_suggestions?: string[]; parse_method: string | null; period_start: string | null; period_end: string | null; rows_total: number; rows_imported: number; rows_duplicate: number; rows_error: number; rows_flagged: number; status: string; message: string | null; issue_counts: Record<string, number>; preview?: { rows: PreviewRow[]; truncated: boolean; sheets: string[] } }
interface Batch { id: number; status: string; created_at: string; committed_at: string | null; created_by: string | null; files_count: number; rows_total: number; rows_imported: number; rows_duplicate: number; rows_error: number; rows_flagged: number; files: FileInfo[] }
interface Issue { id: number; file_id: number; row_number: number | null; severity: string; code: string; message: string; raw: unknown }

const METHOD: Record<string, string> = { excel: "Excel", pdf_table: "PDF (таблица)", pdf_text: "PDF (текст)", pdf_ocr: "PDF (OCR)" };
const STATUS: Record<string, [string, "success" | "muted" | "danger" | "warn"]> = { new: ["новая", "success"], dup_in_file: ["копия в файле", "muted"], dup_in_db: ["уже в базе", "muted"], dup_sheet: ["дубль с др. листа", "muted"], error: ["ошибка", "danger"] };
const SEV: Record<string, "danger" | "warn" | "muted"> = { error: "danger", warning: "warn", info: "muted" };

export default function ImportPage() {
  const { canWrite } = useAuth();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null); const [drag, setDrag] = useState(false);
  const [active, setActive] = useState(0);
  const history = useAsync(() => api.get<Batch[]>("/imports"), []);

  const add = (list: FileList | null) => { if (list) setFiles((p) => [...p, ...Array.from(list)]); };
  async function preview() {
    setBusy(true); setErr(null);
    const fd = new FormData(); files.forEach((f) => fd.append("files", f));
    try { setBatch(await api.upload<Batch>("/imports/preview", fd)); setActive(0); setFiles([]); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function commit() {
    if (!batch) return; setBusy(true); setErr(null);
    try { setBatch(await api.post<Batch>(`/imports/${batch.id}/commit`)); history.reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function cancel() { if (batch) await api.del(`/imports/${batch.id}`).catch(() => undefined); setBatch(null); }

  if (!canWrite) return <><PageHeader title="Импорт данных" /><InfoBox tone="warn">Импорт доступен ролям «Администратор» и «Оператор».</InfoBox><History batches={history.data} canWrite={false} onChanged={history.reload} /></>;
  const done = batch?.status === "committed";
  const failedFiles = batch ? batch.files.filter((f) => f.status === "failed").length : 0;
  const allFailed = !!batch && failedFiles === batch.files.length;
  return (
    <>
      <PageHeader title="Импорт данных" subtitle="Загрузка бюллетеней в формате Excel (.xlsx) и PDF, в том числе сканов (OCR). Станция определяется по имени файла и колонке «Станция»" />
      <ErrorBox message={err} />
      {!batch && (
        <Card className="p-5">
          <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
            onClick={() => input.current?.click()} className={`cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition-colors ${drag ? "border-primary bg-accent" : "border-input hover:bg-muted"}`}>
            <Upload className="mx-auto mb-2 h-8 w-8 text-primary" />
            <div className="text-sm font-medium">Перетащите файлы сюда или нажмите для выбора</div>
            <div className="mt-1 text-xs text-muted-foreground">Можно выбрать сразу несколько файлов · .xlsx, .pdf</div>
            <input ref={input} type="file" multiple accept=".xlsx,.pdf" className="hidden" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          </div>
          {files.length > 0 && (
            <div className="mt-4">
              <ul className="divide-y rounded-md border text-sm">{files.map((f, i) => <li key={i} className="flex items-center justify-between px-3 py-2"><span><FileUp className="mr-2 inline h-4 w-4 text-muted-foreground" />{f.name} <span className="text-xs text-muted-foreground">{fmtSize(f.size)}</span></span><button onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label="Убрать"><X className="h-4 w-4" /></button></li>)}</ul>
              <div className="mt-3 flex justify-end"><Button onClick={preview} disabled={busy}>{busy ? <Spinner /> : null} Загрузить и проверить ({files.length})</Button></div>
            </div>
          )}
        </Card>
      )}

      {batch && (
        <>
          {done && batch.rows_imported === 0 ? <InfoBox tone="warn">Ничего не добавлено в базу. Дубликатов: {batch.rows_duplicate}, ошибок: {batch.rows_error}. Если файл не загрузился, проверьте станцию файла и журнал ниже.</InfoBox>
            : done ? <InfoBox><CheckCircle2 className="mr-1 inline h-4 w-4" /> Импорт завершён: добавлено {batch.rows_imported} записей. Пропущено дубликатов: {batch.rows_duplicate}, ошибок: {batch.rows_error}.</InfoBox>
            : <InfoBox tone="warn">Предварительный просмотр. В базу ничего ещё не записано — проверьте результат и нажмите «Импортировать».</InfoBox>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatCard label="Строк в файлах" value={batch.rows_total} />
            <StatCard label={done ? "Импортировано" : "Будет добавлено"} value={batch.rows_imported} />
            <StatCard label="Дубликатов (пропуск)" value={batch.rows_duplicate} />
            <StatCard label="Ошибочных" value={batch.rows_error} tone={batch.rows_error ? "warn" : undefined} />
            <StatCard label="Помечено для проверки" value={batch.rows_flagged} tone={batch.rows_flagged ? "warn" : undefined} />
          </div>
          <div className="mt-4 flex flex-wrap gap-1.5 border-b">
            {batch.files.map((f, i) => <button key={f.id} onClick={() => setActive(i)} className={`-mb-px border-b-2 px-3 py-2 text-sm ${i === active ? "border-primary font-semibold text-primary" : "border-transparent text-muted-foreground"}`}>{f.station_code ?? "?"} <span className="text-xs">· {f.original_name}</span></button>)}
          </div>
          <FilePanel key={`${batch.files[active].id}-${batch.files[active].station_code}-${batch.status}`} batchId={batch.id} f={batch.files[active]} editable={!done} onBatch={setBatch} />
          {!done && allFailed && <InfoBox tone="warn">Импортировать пока нечего: у файла не определена станция (или он не читается). Выберите станцию в жёлтом блоке выше — после этого появятся строки для проверки и кнопка «Импортировать» станет активной.</InfoBox>}
          {!done && !allFailed && failedFiles > 0 && <InfoBox tone="warn">Файлов, которые будут пропущены из-за ошибок: {failedFiles}. Остальные будут импортированы.</InfoBox>}
          <div className="mt-4 flex justify-end gap-2">
            {done ? <Button onClick={() => setBatch(null)}>Загрузить ещё</Button> : <><Button variant="outline" onClick={cancel} disabled={busy}>Отмена</Button><Button onClick={commit} disabled={busy || allFailed}>{busy ? <Spinner /> : null} Импортировать</Button></>}
          </div>
        </>
      )}
      <History batches={history.data} canWrite={canWrite} onChanged={history.reload} />
    </>
  );
}

function FilePanel({ batchId, f, editable, onBatch }: { batchId: number; f: FileInfo; editable: boolean; onBatch: (b: Batch) => void }) {
  const [sev, setSev] = useState("");
  const [sheet, setSheet] = useState(""); const [status, setStatus] = useState("");
  const [stInput, setStInput] = useState(f.station_hint ?? f.station_code ?? ""); const [stErr, setStErr] = useState<string | null>(null);
  const stations = useAsync(() => api.get<Station[]>("/stations"), []);
  async function applyStation(code: string | null) {
    setStErr(null);
    try { onBatch(await api.patch<Batch>(`/imports/${batchId}/files/${f.id}`, { station_code: code })); } catch (e) { setStErr((e as Error).message); }
  }
  const issues = useAsync(() => api.get<{ total: number; items: Issue[] }>(`/imports/${batchId}/issues`, { file_id: f.id, severity: sev, page_size: 200 }), [batchId, f.id, sev, f.status]);
  const all = f.preview?.rows ?? [];
  const sheets = f.preview?.sheets ?? [];
  const filtered = all.filter((r) => (!sheet || r.sheet === sheet) && (!status || r.status === status));
  const rows = filtered.slice(0, 500);
  return (
    <div className="mt-4 space-y-4">
      {editable && !f.station_code && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <div className="font-semibold">Станция файла не определена — без неё файл не будет импортирован.</div>
          <div className="mt-1">Выберите станцию{(f.station_suggestions?.length ?? 0) > 0 ? " (подобрана по названию файла)" : ""} или впишите код ниже и нажмите «Задать станцию файлу»:</div>
          {(f.station_suggestions?.length ?? 0) > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {f.station_suggestions!.map((c) => <Button key={c} size="sm" onClick={() => applyStation(c)}>Использовать {c}</Button>)}
            </div>
          )}
        </div>
      )}
      <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-sm">
        <div><span className="text-muted-foreground">Файл:</span> {f.original_name} ({fmtSize(f.size_bytes)})</div>
        <div><span className="text-muted-foreground">Станция:</span> <b>{f.station_code ?? "не определена"}</b>{f.station_hint && <span className="text-xs text-muted-foreground"> (задана вручную)</span>}</div>
        {editable && (
          <div className="flex items-center gap-1.5">
            <Input list={`st-${f.id}`} className="h-8 w-28" placeholder="код" value={stInput} onChange={(e) => setStInput(e.target.value.toUpperCase())} />
            <datalist id={`st-${f.id}`}>{stations.data?.map((x) => <option key={x.code} value={x.code} />)}</datalist>
            <Button size="sm" variant="outline" disabled={!/^[A-Z][A-Z0-9]{1,7}$/.test(stInput)} onClick={() => applyStation(stInput)}>Задать станцию файлу</Button>
            {f.station_hint && <Button size="sm" variant="ghost" onClick={() => applyStation(null)}>Авто</Button>}
          </div>
        )}
        {stErr && <Badge variant="danger">{stErr}</Badge>}
        <div><span className="text-muted-foreground">Метод:</span> {f.parse_method ? METHOD[f.parse_method] : "—"}</div>
        <div><span className="text-muted-foreground">Период:</span> {f.period_start ? `${fmtDate(f.period_start)} – ${fmtDate(f.period_end)}` : "—"}</div>
        <div>Строк {f.rows_total} · новых {f.rows_imported} · дубликатов {f.rows_duplicate} · ошибок {f.rows_error} · помечено {f.rows_flagged}</div>
        {f.message && <Badge variant="danger">{f.message}</Badge>}
        {f.rows_total === 0 && !f.message && <Badge variant="muted">В файле нет записей</Badge>}
      </Card>
      {rows.length > 0 && (<>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-semibold">Записи ({filtered.length}{f.preview?.truncated ? "+" : ""})</h3>
          {sheets.length > 1 && <Select className="h-8 w-44" value={sheet} onChange={(e) => setSheet(e.target.value)}><option value="">Все листы ({sheets.length})</option>{sheets.map((x) => <option key={x} value={x}>{x}</option>)}</Select>}
          <Select className="h-8 w-44" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Все статусы</option>{Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</Select>
          {filtered.length > 500 && <span className="text-xs text-muted-foreground">показаны первые 500 — уточните фильтр</span>}
        </div>
        <div className="max-h-[420px] overflow-auto rounded-md border">
          <Table><THead><TR>{sheets.length > 1 && <TH>Лист</TH>}<TH>Стр.</TH><TH>Статус</TH><TH>Дата</TH><TH>P</TH><TH>Очаг</TH><TH className="text-right">S-P</TH><TH className="text-right">R</TH><TH className="text-right">Mb</TH><TH className="text-right">ML</TH><TH>Проверка</TH></TR></THead>
            <TBody>{rows.map((r) => (
              <TR key={r.source_row} className={r.status === "new" ? (r.flags.length ? "bg-amber-50/60" : "") : "text-muted-foreground"}>
                {sheets.length > 1 && <TD>{r.sheet}</TD>}<TD>{r.source_row}</TD><TD><Badge variant={STATUS[r.status][1]}>{STATUS[r.status][0]}</Badge></TD>
                <TD>{fmtDate(r.event_date)}</TD><TD>{r.p_phase} {fmtTime(r.p_time)}</TD><TD>{fmtTime(r.origin_time)}</TD>
                <TD className="text-right">{fmtNum(r.s_minus_p === null ? null : Number(r.s_minus_p), 2)}</TD><TD className="text-right">{fmtNum(r.r_km === null ? null : Number(r.r_km), 1)}</TD>
                <TD className="text-right">{fmtNum(r.mb === null ? null : Number(r.mb), 1)}</TD><TD className="text-right">{fmtNum(r.ml === null ? null : Number(r.ml), 1)}</TD>
                <TD className="whitespace-normal">{r.error ? <Badge variant="danger">{r.error}</Badge> : r.flags.length ? <ReasonBadges reasons={r.flags} /> : ""}</TD>
              </TR>))}</TBody></Table>
        </div></>)}
      <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">Журнал файла ({issues.data?.total ?? 0})</h3>
        <div className="flex gap-1">{["", "error", "warning", "info"].map((s) => <button key={s} onClick={() => setSev(s)} className={`rounded-full border px-3 py-0.5 text-xs ${sev === s ? "border-primary bg-primary text-white" : "bg-white"}`}>{s ? { error: "Ошибки", warning: "Предупреждения", info: "Инфо" }[s] : "Все"}</button>)}</div></div>
      {issues.data && issues.data.items.length > 0 && <div className="max-h-72 overflow-auto rounded-md border bg-white text-sm">{issues.data.items.map((i) => <div key={i.id} className="flex gap-3 border-b px-3 py-1.5 last:border-0"><Badge variant={SEV[i.severity]}>{i.severity}</Badge><span className="w-14 shrink-0 text-muted-foreground">{i.row_number ? `стр. ${i.row_number}` : ""}</span><span>{i.message}</span></div>)}</div>}
    </div>
  );
}

function History({ batches, canWrite, onChanged }: { batches: Batch[] | null; canWrite: boolean; onChanged: () => void }) {
  async function rollback(b: Batch) {
    if (!confirm(`Откатить импорт №${b.id}?\n\nБудут удалены все записи, добавленные этим импортом (${b.rows_imported}), включая изменённые вручную. Файлы можно будет импортировать заново.`)) return;
    try { await api.post(`/imports/${b.id}/rollback`); onChanged(); } catch (e) { alert((e as Error).message); }
  }
  return (
    <>
      <h2 className="mb-2 mt-8 text-sm font-semibold">История импортов</h2>
      <Table><THead><TR><TH>№</TH><TH>Дата</TH><TH>Пользователь</TH><TH>Файлы</TH><TH>Строк</TH><TH>Добавлено</TH><TH>Дубликатов</TH><TH>Ошибок</TH><TH>Статус</TH><TH /></TR></THead>
        <TBody>{batches?.map((b) => <TR key={b.id}><TD>{b.id}</TD><TD>{fmtDateTime(b.committed_at ?? b.created_at)}</TD><TD>{b.created_by ?? "—"}</TD>
          <TD className="whitespace-normal">{b.files.map((f) => f.original_name).join(", ")}</TD><TD>{b.rows_total}</TD><TD>{b.rows_imported}</TD><TD>{b.rows_duplicate}</TD><TD>{b.rows_error}</TD>
          <TD><Badge variant={b.status === "committed" ? "success" : b.status === "rolled_back" ? "muted" : "danger"}>{b.status === "committed" ? "Выполнен" : b.status === "rolled_back" ? "Откачен" : "Отменён (ошибка)"}</Badge></TD>
          <TD>{canWrite && b.status === "committed" && <Button variant="ghost" size="sm" onClick={() => rollback(b)}>Откатить</Button>}</TD></TR>)}
          {batches && !batches.length && <TR><TD colSpan={10} className="text-muted-foreground">Импортов ещё не было</TD></TR>}</TBody></Table>
    </>
  );
}
