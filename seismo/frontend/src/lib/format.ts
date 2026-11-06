export const fmtDate = (d?: string | null) => (d ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}` : "—");
export const fmtTime = (t?: string | null) => (t ? t.replace(".", ",") : "—");
export const fmtNum = (v: number | null | undefined, digits: number) =>
  v === null || v === undefined ? "—" : v.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const fmtDateTime = (s?: string | null) => {
  if (!s) return "—";
  const d = new Date(s);
  return `${d.toLocaleDateString("ru-RU")} ${d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
};
export const fmtSize = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(b / 1024))} КБ`);

const FIELDS: Record<string, string> = {
  no: "No", p_phase: "фаза P", s_phase: "фаза S", p_time: "время P", s_time: "время S", origin_time: "время в очаге",
  s_minus_p: "S-P", r_km: "R км", amp_p: "A(P)", amp_s: "A(S)", mb: "Mb", ml: "ML", ep_vp: "Ep Vp", ep_vs: "Ep Vs", ep_vp_vs: "Ep Vp/Vs",
};
const REASONS: Record<string, string> = {
  ocr: "Распознано OCR — проверьте значения",
  station_mismatch: "Код станции в строке не совпадает со станцией файла",
  near_duplicate: "Возможный дубль: то же время вступления P, но другие значения",
  time_order: "Нарушен порядок времён (P / S / время в очаге)",
  sp_mismatch: "S-P не согласуется с разностью времён S и P",
  mag_range: "Магнитуда вне физически возможного диапазона",
  amp_range: "Аномально большая амплитуда (>1000 мк/с)",
  vel_range: "Скорость Ep Vp/Vs вне допустимого диапазона",
  vpvs_range: "Ep Vp/Vs вне диапазона 1.5–2.1",
  dist_range: "Расстояние более 3000 км",
  date_outlier: "Дата резко выбивается из соседних записей листа — возможна опечатка (год/месяц)",
  manual: "Помечено вручную",
};
export function reasonText(code: string): string {
  if (REASONS[code]) return REASONS[code];
  const [kind, field] = code.split(":");
  const f = FIELDS[field] ?? field;
  if (kind === "parse") return `Не удалось распознать значение: ${f} (в базе NULL, исходник сохранён)`;
  if (kind === "excel_error") return `В исходном файле ошибка Excel (#VALUE! и т.п.): ${f} — значение не получено (в базе NULL)`;
  if (kind === "missing") return `Значение отсутствует: ${f}`;
  return code;
}
export const isoToday = () => new Date().toISOString().slice(0, 10);
