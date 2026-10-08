import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./context";
import DashboardPage from "./pages/DashboardPage";
import ExpenseFormPage from "./pages/ExpenseFormPage";
import ExpensesPage from "./pages/ExpensesPage";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <div className="boot">Loading…</div>;

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="expenses" element={<ExpensesPage />} />
        <Route path="expenses/new" element={<ExpenseFormPage />} />
        <Route path="expenses/:id" element={<ExpenseFormPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
