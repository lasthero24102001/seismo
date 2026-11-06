export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

function qs(params?: Params): string {
  if (!params) return "";
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, opts: { params?: Params; body?: unknown; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method, credentials: "include", headers: {} };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}${qs(opts.params)}`, init);
  } catch {
    throw new ApiError(0, "Нет связи с сервером");
  }
  if (res.status === 401 && !path.startsWith("/auth/login")) window.dispatchEvent(new Event("unauthorized"));
  if (!res.ok) {
    let msg = `Ошибка ${res.status}`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch { /* пустой ответ */ }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(path: string, params?: Params) => request<T>("GET", path, { params }),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: (path: string) => request<void>("DELETE", path),
  upload: <T,>(path: string, form: FormData) => request<T>("POST", path, { form }),
  async download(path: string, params: Params | undefined, fallbackName: string) {
    const res = await fetch(`/api${path}${qs(params)}`, { credentials: "include" });
    if (!res.ok) {
      let msg = `Ошибка ${res.status}`;
      try { msg = (await res.json()).detail ?? msg; } catch { /* */ }
      throw new ApiError(res.status, msg);
    }
    const cd = res.headers.get("Content-Disposition") ?? "";
    const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  },
};

export type Role = "admin" | "operator" | "viewer";
export interface User { id: number; username: string; full_name: string | null; role: Role; is_active: boolean; created_at?: string; last_login_at?: string | null }
export interface Station { id: number; code: string; name: string | null; aliases: string[]; is_active: boolean; events_count: number; flagged_count: number; first_date: string | null; last_date: string | null }
export interface SeismicEvent {
  id: number; station_code: string; station_name: string | null; source_no: number | null; event_date: string;
  p_phase: string | null; p_time: string | null; s_phase: string | null; s_time: string | null; origin_time: string | null;
  s_minus_p: number | null; r_km: number | null; amp_p: number | null; amp_s: number | null; mb: number | null; ml: number | null;
  ep_vp: number | null; ep_vs: number | null; ep_vp_vs: number | null; needs_review: boolean; review_reasons: string[]; review_comment: string | null;
}
export interface EventDetail extends SeismicEvent { file_id: number | null; file_name: string | null; source_row: number | null; source_sheet: string | null; raw: unknown[] | null; record_hash: string; created_at: string; updated_at: string | null }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
