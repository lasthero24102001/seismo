import { History, Pencil, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ErrorBox, ReasonBadges, Spinner } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { api, type EventDetail, type Station } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtDateTime, fmtNum, fmtTime } from "@/lib/format";

type Kind = "text" | "time" | "num" | "date";
const FIELDS: { k: keyof EventDetail; label: string; kind: Kind; digits?: number }[] = [
  { k: "event_date", label: "Дата", kind: "date" },
  { k: "p_phase", label: "Фаза P", kind: "text" }, { k: "p_time", label: "Время P", kind: "time" },
  { k: "s_phase", label: "Фаза S", kind: "text" }, { k: "s_time", label: "Время S", kind: "time" },
  { k: "origin_time", label: "Время в очаге", kind: "time" },
  { k: "s_minus_p", label: "S-P, с", kind: "num", digits: 2 }, { k: "r_km", label: "R км", kind: "num", digits: 1 },
  { k: "amp_p", label: "A(P) мк/с", kind: "num", digits: 2 }, { k: "amp_s", label: "A(S) мк/с", kind: "num", digits: 2 },
  { k: "mb", label: "Mb", kind: "num", digits: 1 }, { k: "ml", label: "ML", kind: "num", digits: 1 },
  { k: "ep_vp", label: "Ep Vp", kind: "num", digits: 2 }, { k: "ep_vs", label: "Ep Vs", kind: "num", digits: 2 },
  { k: "ep_vp_vs", label: "Ep Vp/Vs", kind: "num", digits: 2 },
];
const LABEL: Record<string, string> = { ...Object.fromEntries(FIELDS.map((f) => [f.k, f.label])), station: "Станция", review_comment: "Комментарий", needs_review: "Проверка" };
const TIME_FIELDS = new Set(["p_time", "s_time", "origin_time"]);

interface Hist { id: number; created_at: string; username: string | null; changes: Record<string, [unknown, unknown]> }

// «чч:мм:сс,т» или «чч:мм:сс.т» → секунды
function toSec(v: string): number | null {
  const m = /^\s*(\d{1,2})[:;](\d{2})[:;](\d{2})(?:[,.](\d+))?\s*$/.exec(v);
  return m ? +m[1] * 3600 + +m[2] * 60 + +m[3] + (m[4] ? +`0.${m[4]}` : 0) : null;
}
const show = (k: string, v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (k === "needs_review") return v ? "требуется" : "не требуется";
  if (TIME_FIELDS.has(k)) return fmtTime(String(v));
  if (k === "event_date") return fmtDate(String(v));
  return String(v);
};

interface Props { id: number | null; onClose: () => void; onChanged: () => void }

export default function EventDialog({ id, onClose, onChanged }: Props) {
  const { canWrite } = useAuth();
  const [ev, setEv] = useState<EventDetail | null>(null);
  const [hist, setHist] = useState<Hist[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [initial, setInitial] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"auto" | "true" | "false">("auto");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadHist = (eid: number) => api.get<Hist[]>(`/events/${eid}/history`).then(setHist).catch(() => setHist([]));
  useEffect(() => {
    setEv(null); setEdit(false); setErr(null); setHist([]);
    if (id) { api.get<EventDetail>(`/events/${id}`).then(setEv).catch((e) => setErr(e.message)); loadHist(id); }
  }, [id]);

  function snapshot(e: EventDetail): Record<string, string> {
    const o: Record<string, string> = { station_code: e.station_code, review_comment: e.review_comment ?? "" };
    FIELDS.forEach(({ k, kind }) => {
      const v = e[k];
      o[k] = v === null || v === undefined ? "" : kind === "time" ? fmtTime(String(v)) : String(v);
    });
    return o;
  }
  function startEdit() {
    if (!ev) return;
    const o = snapshot(ev);
    setForm(o); setInitial(o); setStatus("auto"); setErr(null); setEdit(true);
    if (!stations.length) api.get<Station[]>("/stations").then(setStations).catch(() => undefined);
  }

  // подсказка S − P по введённым временам (в базу не пишется, пока пользователь не нажмёт «подставить»)
  const calc = useMemo(() => {
    const p = toSec(form.p_time ?? ""), s = toSec(form.s_time ?? "");
    return p !== null && s !== null ? Math.round((s - p) * 10) / 10 : null;
  }, [form.p_time, form.s_time]);
  const spNow = parseFloat((form.s_minus_p ?? "").replace(",", "."));

  const changed = edit ? Object.keys(form).filter((k) => form[k] !== initial[k]) : [];

  async function save() {
    if (!ev) return;
    setBusy(true); setErr(null);
    try {
      const body: Record<string, unknown> = {};
      changed.forEach((k) => { body[k] = k === "review_comment" ? form[k] || null : form[k].trim() === "" ? null : form[k].trim(); });
      if (status !== "auto") body.needs_review = status === "true";
      if (!Object.keys(body).length) { setEdit(false); return; }
      setEv(await api.patch<EventDetail>(`/events/${ev.id}`, body));
      setEdit(false); loadHist(ev.id); onChanged();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!ev || !confirm("Удалить запись безвозвратно? Действие будет записано в журнал.")) return;
    try { await api.del(`/events/${ev.id}`); onClose(); onChanged(); } catch (e) { setErr((e as Error).message); }
  }
  const view = (k: keyof EventDetail, kind: Kind, digits?: number) => {
    const v = ev![k] as never;
    return kind === "date" ? fmtDate(v) : kind === "time" ? fmtTime(v) : kind === "num" ? fmtNum(v, digits ?? 2) : (v ?? "—");
  };

  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={ev ? `Запись ${ev.station_code} · ${fmtDate(ev.event_date)} ${fmtTime(ev.p_time)}` : "Запись"} className="max-w-3xl">
        {!ev ? (err ? <ErrorBox message={err} /> : <Spinner />) : (
          <div className="space-y-4">
            <ErrorBox message={err} />
            {ev.needs_review && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
                <div className="mb-2 text-xs font-semibold text-amber-900">Требует проверки</div>
                <ReasonBadges reasons={ev.review_reasons} />
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {edit && canWrite && (
                <div><Label>Станция</Label>
                  <Input list="ev-stations" value={form.station_code} onChange={(e) => setForm({ ...form, station_code: e.target.value.toUpperCase() })} />
                  <datalist id="ev-stations">{stations.map((s) => <option key={s.code} value={s.code} />)}</datalist></div>
              )}
              {FIELDS.map(({ k, label, kind }) => (
                <div key={k}>
                  <Label>{label}</Label>
                  {edit ? (
                    <Input value={form[k]} type={kind === "date" ? "date" : "text"} inputMode={kind === "num" ? "decimal" : undefined}
                      className={form[k] !== initial[k] ? "border-primary ring-1 ring-primary/40" : ""}
                      placeholder={kind === "time" ? "чч:мм:сс,т" : ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                  ) : <div className="text-sm font-medium">{view(k, kind, FIELDS.find((f) => f.k === k)?.digits) as string}</div>}
                  {edit && k === "s_minus_p" && calc !== null && (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      S − P по временам = <b>{calc.toFixed(1)} с</b>{" "}
                      {Number.isNaN(spNow) || Math.abs(spNow - calc) > 0.25
                        ? <button type="button" className="text-primary underline" onClick={() => setForm({ ...form, s_minus_p: calc.toFixed(1) })}>подставить</button>
                        : <span className="text-emerald-600">✓ совпадает</span>}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {edit ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div><Label>Статус проверки</Label>
                  <Select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
                    <option value="auto">Определить автоматически по новым значениям</option>
                    <option value="false">Проверено вручную (снять пометку)</option>
                    <option value="true">Требует проверки</option>
                  </Select></div>
                <div><Label>Комментарий</Label><Input value={form.review_comment} onChange={(e) => setForm({ ...form, review_comment: e.target.value })} /></div>
                <p className="text-xs text-muted-foreground sm:col-span-2">Время вводите как в бюллетене: <code>01:59:27,0</code>. После сохранения проверки (порядок времён, S-P, диапазоны) пересчитаются; если замечаний нет — пометка снимется сама. Исходная строка из файла останется неизменной.</p>
              </div>
            ) : ev.review_comment && <div className="text-sm"><span className="text-muted-foreground">Комментарий: </span>{ev.review_comment}</div>}

            <div className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              <div>Источник: {ev.file_name ?? "—"}{ev.source_sheet ? `, лист «${ev.source_sheet}»` : ""}{ev.source_row ? `, строка ${ev.source_row}` : ""}{ev.source_no ? `, № ${ev.source_no}` : ""} · импорт {fmtDateTime(ev.created_at)}{ev.updated_at && ` · изменено ${fmtDateTime(ev.updated_at)}`}</div>
              {ev.raw && <div className="overflow-x-auto rounded bg-muted p-2 font-mono text-[11px]">Исходная строка: {JSON.stringify(ev.raw)}</div>}
            </div>

            {hist.length > 0 && (
              <div className="border-t pt-3">
                <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><History className="h-3.5 w-3.5" /> История изменений ({hist.length})</div>
                <ul className="max-h-44 space-y-2 overflow-auto text-xs">
                  {hist.map((h) => (
                    <li key={h.id} className="rounded border bg-slate-50 p-2">
                      <div className="mb-1 text-muted-foreground">{fmtDateTime(h.created_at)} · {h.username ?? "—"}</div>
                      {Object.entries(h.changes).filter(([k]) => k !== "review_reasons").map(([k, [a, b]]) => (
                        <div key={k}><span className="font-medium">{LABEL[k] ?? k}:</span> <span className="text-red-600 line-through">{show(k, a)}</span> → <span className="text-emerald-700">{show(k, b)}</span></div>
                      ))}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {canWrite && (
              <div className="flex justify-between">
                <Button variant="destructive" size="sm" onClick={remove}><Trash2 className="h-4 w-4" /> Удалить</Button>
                {edit ? (
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setEdit(false)}>Отмена</Button>
                    <Button size="sm" onClick={save} disabled={busy || (changed.length === 0 && status === "auto")}><Save className="h-4 w-4" /> Сохранить{changed.length ? ` (${changed.length})` : ""}</Button>
                  </div>
                ) : <Button variant="outline" size="sm" onClick={startEdit}><Pencil className="h-4 w-4" /> Редактировать</Button>}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
