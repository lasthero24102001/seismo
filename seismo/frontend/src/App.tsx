import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/Layout";
import { Spinner } from "@/components/common";
import { AuthProvider, useAuth } from "@/lib/auth";
import Dashboard from "@/pages/Dashboard";
import Events from "@/pages/Events";
import ImportPage from "@/pages/Import";
import Login from "@/pages/Login";
import Reports from "@/pages/Reports";
import SettingsPage from "@/pages/Settings";
import Stations from "@/pages/Stations";
import UsersPage from "@/pages/Users";

function Guard() {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center"><Spinner /></div>;
  if (!user) return <Login />;
  return <Layout />;
}

function AdminOnly({ children }: { children: JSX.Element }) {
  const { isAdmin } = useAuth();
  return isAdmin ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Guard />}>
            <Route index element={<Dashboard />} />
            <Route path="events" element={<Events />} />
            <Route path="stations" element={<Stations />} />
            <Route path="import" element={<ImportPage />} />
            <Route path="reports" element={<Reports />} />
            <Route path="users" element={<AdminOnly><UsersPage /></AdminOnly>} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
