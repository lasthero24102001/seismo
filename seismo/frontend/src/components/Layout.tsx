import { Activity, BarChart3, Database, FileSpreadsheet, LayoutDashboard, LogOut, Menu, Radio, Settings, Upload, Users, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Button } from "./ui/button";

const ROLE = { admin: "Администратор", operator: "Оператор", viewer: "Наблюдатель" } as const;

export default function Layout() {
  const { user, logout, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const items = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/events", label: "Сейсмологические данные", icon: Database },
    { to: "/stations", label: "Сейсмостанции", icon: Radio },
    { to: "/import", label: "Импорт данных", icon: Upload },
    { to: "/reports", label: "Отчёты", icon: FileSpreadsheet },
    ...(isAdmin ? [{ to: "/users", label: "Пользователи", icon: Users }] : []),
    { to: "/settings", label: "Настройки", icon: Settings },
  ];
  return (
    <div className="min-h-screen lg:flex">
      <aside className={`${open ? "block" : "hidden"} fixed inset-0 z-40 bg-white lg:static lg:block lg:w-64 lg:shrink-0 lg:border-r`}>
        <div className="flex h-14 items-center justify-between border-b px-5">
          <div className="flex items-center gap-2 font-semibold text-primary"><Activity className="h-5 w-5" /> Seismo</div>
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(false)}><X className="h-4 w-4" /></Button>
        </div>
        <nav className="space-y-1 p-3">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
              className={({ isActive }) => `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${isActive ? "bg-accent text-accent-foreground" : "text-slate-600 hover:bg-muted"}`}>
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex h-14 items-center justify-between border-b bg-white px-4 lg:px-8">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Меню"><Menu className="h-5 w-5" /></Button>
          <div className="hidden items-center gap-2 text-sm text-muted-foreground lg:flex"><BarChart3 className="h-4 w-4" /> Учёт и анализ сейсмологических бюллетеней</div>
          <div className="flex items-center gap-3">
            <div className="text-right text-sm leading-tight">
              <div className="font-medium">{user?.full_name || user?.username}</div>
              <div className="text-xs text-muted-foreground">{user && ROLE[user.role]}</div>
            </div>
            <Button variant="outline" size="sm" onClick={logout}><LogOut className="h-4 w-4" /> Выйти</Button>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] p-4 lg:p-8"><Outlet /></main>
      </div>
    </div>
  );
}
