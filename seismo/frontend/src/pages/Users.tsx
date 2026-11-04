import { KeyRound, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ErrorBox, PageHeader, Spinner } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type Role, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

const ROLES: Record<Role, string> = { admin: "Администратор", operator: "Оператор (импорт, правка)", viewer: "Наблюдатель (только чтение)" };

export default function UsersPage() {
  const { user: me } = useAuth();
  const { data, error, reload } = useAsync(() => api.get<User[]>("/users"), []);
  const [dlg, setDlg] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", full_name: "", password: "", role: "viewer" as Role });

  async function create() {
    setErr(null);
    try { await api.post("/users", { ...form, full_name: form.full_name || null }); setDlg(false); setForm({ username: "", full_name: "", password: "", role: "viewer" }); reload(); } catch (e) { setErr((e as Error).message); }
  }
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); reload(); } catch (e) { alert((e as Error).message); } };
  return (
    <>
      <PageHeader title="Пользователи" subtitle="Создание, роли и удаление учётных записей" actions={<Button onClick={() => { setErr(null); setDlg(true); }}><Plus className="h-4 w-4" /> Создать пользователя</Button>} />
      <ErrorBox message={error} />
      {!data ? <Spinner /> : (
        <Table><THead><TR><TH>Логин</TH><TH>Имя</TH><TH>Роль</TH><TH>Статус</TH><TH>Последний вход</TH><TH /></TR></THead>
          <TBody>{data.map((u) => (
            <TR key={u.id}><TD className="font-medium">{u.username}</TD><TD>{u.full_name || "—"}</TD>
              <TD><Select className="h-8 w-56" value={u.role} disabled={u.id === me?.id} onChange={(e) => act(() => api.patch(`/users/${u.id}`, { role: e.target.value }))}>{(Object.keys(ROLES) as Role[]).map((r) => <option key={r} value={r}>{ROLES[r]}</option>)}</Select></TD>
              <TD><Badge variant={u.is_active ? "success" : "muted"}>{u.is_active ? "Активен" : "Отключён"}</Badge></TD>
              <TD>{fmtDateTime(u.last_login_at)}</TD>
              <TD className="text-right"><div className="flex justify-end gap-1">
                <Button variant="ghost" size="icon" title="Сбросить пароль" onClick={() => { const p = prompt(`Новый пароль для ${u.username} (мин. 8 символов):`); if (p) act(() => api.patch(`/users/${u.id}`, { password: p })); }}><KeyRound className="h-4 w-4" /></Button>
                {u.id !== me?.id && <Button variant="ghost" size="sm" onClick={() => act(() => api.patch(`/users/${u.id}`, { is_active: !u.is_active }))}>{u.is_active ? "Отключить" : "Включить"}</Button>}
                {u.id !== me?.id && <Button variant="ghost" size="icon" title="Удалить" onClick={() => confirm(`Удалить пользователя ${u.username}?`) && act(() => api.del(`/users/${u.id}`))}><Trash2 className="h-4 w-4 text-destructive" /></Button>}
              </div></TD></TR>))}</TBody></Table>
      )}
      <Dialog open={dlg} onOpenChange={setDlg}>
        <DialogContent title="Новый пользователь">
          <ErrorBox message={err} />
          <div className="space-y-3">
            <div><Label>Логин (латиница, цифры, . _ -)</Label><Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
            <div><Label>Имя</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
            <div><Label>Пароль (не менее 8 символов)</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
            <div><Label>Роль</Label><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{(Object.keys(ROLES) as Role[]).map((r) => <option key={r} value={r}>{ROLES[r]}</option>)}</Select></div>
            <div className="flex justify-end gap-2 pt-2"><Button variant="outline" onClick={() => setDlg(false)}>Отмена</Button><Button onClick={create}>Создать</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
