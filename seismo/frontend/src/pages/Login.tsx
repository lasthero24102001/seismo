import { Activity } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";

export default function Login() {
  const { login } = useAuth();
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await login(username.trim(), password); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-6 flex flex-col items-center gap-2">
          <div className="rounded-full bg-accent p-3 text-primary"><Activity className="h-6 w-6" /></div>
          <h1 className="text-lg font-semibold">Seismo</h1>
          <p className="text-center text-sm text-muted-foreground">Учёт и анализ сейсмологических бюллетеней</p>
        </div>
        <ErrorBox message={error} />
        <form onSubmit={submit} className="space-y-4">
          <div><Label htmlFor="u">Логин</Label><Input id="u" autoFocus autoComplete="username" value={username} onChange={(e) => setU(e.target.value)} required /></div>
          <div><Label htmlFor="p">Пароль</Label><Input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setP(e.target.value)} required /></div>
          <Button className="w-full" disabled={busy}>{busy ? "Вход…" : "Войти"}</Button>
        </form>
      </Card>
    </div>
  );
}
