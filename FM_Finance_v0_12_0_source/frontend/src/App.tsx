import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./context";
import AccountsPage from "./pages/AccountsPage";
import BankingPage from "./pages/BankingPage";
import BillFormPage from "./pages/BillFormPage";
import BillsPage from "./pages/BillsPage";
import ChartOfAccountsPage from "./pages/ChartOfAccountsPage";
import CustomersPage from "./pages/CustomersPage";
import InvoiceFormPage from "./pages/InvoiceFormPage";
import InvoicesPage from "./pages/InvoicesPage";
import PlansPage from "./pages/PlansPage";
import ProductsPage from "./pages/ProductsPage";
import ReceivePaymentPage from "./pages/ReceivePaymentPage";
import JournalPage from "./pages/JournalPage";
import ReportsPage from "./pages/ReportsPage";
import DashboardPage from "./pages/DashboardPage";
import ExpenseFormPage from "./pages/ExpenseFormPage";
import ExpensesPage from "./pages/ExpensesPage";
import CompaniesPage from "./pages/CompaniesPage";
import ImportPage from "./pages/ImportPage";
import NoCompanyPage from "./pages/NoCompanyPage";
import ResellersPage from "./pages/ResellersPage";
import TeamPage from "./pages/TeamPage";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";
import RulesPage from "./pages/RulesPage";
import BankRulesPage from "./pages/BankRulesPage";
import UpdatesPage from "./pages/UpdatesPage";
import BackupsPage from "./pages/BackupsPage";
import OwnerFundsPage from "./pages/OwnerFundsPage";
import ReconcilePage from "./pages/ReconcilePage";
import AccountantPage from "./pages/AccountantPage";

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

  if (user.role === "none") {
    return (
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<NoCompanyPage />} />
          <Route path="companies" element={<CompaniesPage />} />
          {user.is_platform_admin && <Route path="resellers" element={<ResellersPage />} />}
          {user.is_platform_admin && <Route path="updates" element={<UpdatesPage />} />}
          {user.is_platform_admin && <Route path="backups" element={<BackupsPage />} />}
          {(user.is_platform_admin || user.is_reseller_admin) && <Route path="plans" element={<PlansPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    );
  }

  // Bills, the chart of accounts, journal entries and reports are for owners, accountants and bookkeepers.
  const books = user.role === "admin" || user.role === "approver";

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="expenses" element={<ExpensesPage />} />
        <Route path="expenses/new" element={<ExpenseFormPage />} />
        <Route path="expenses/:id" element={<ExpenseFormPage />} />
        <Route path="banking" element={<BankingPage />} />
        <Route path="banking/import" element={<ImportPage />} />
        {books && <Route path="banking/rules" element={<BankRulesPage />} />}
        <Route path="accounts" element={<AccountsPage />} />
        {books && <Route path="bills" element={<BillsPage />} />}
        {books && <Route path="bills/new" element={<BillFormPage />} />}
        {books && <Route path="bills/:id" element={<BillFormPage />} />}
        {books && <Route path="chart-of-accounts" element={<ChartOfAccountsPage />} />}
        {books && <Route path="chart-of-accounts/:id" element={<ChartOfAccountsPage />} />}
        {books && <Route path="journal" element={<JournalPage />} />}
        {books && <Route path="journal/:id" element={<JournalPage />} />}
        {books && <Route path="owner-funds" element={<OwnerFundsPage />} />}
        {books && <Route path="reconcile" element={<ReconcilePage />} />}
        {books && <Route path="reconcile/:id" element={<ReconcilePage />} />}
        {books && <Route path="accountant" element={<AccountantPage />} />}
        {books && <Route path="reports" element={<ReportsPage />} />}
        {books && <Route path="invoices" element={<InvoicesPage />} />}
        {books && <Route path="invoices/new" element={<InvoiceFormPage />} />}
        {books && <Route path="invoices/:id" element={<InvoiceFormPage />} />}
        {books && <Route path="payments/new" element={<ReceivePaymentPage />} />}
        {books && <Route path="customers" element={<CustomersPage />} />}
        {books && <Route path="customers/:id" element={<CustomersPage />} />}
        {books && <Route path="products" element={<ProductsPage />} />}
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/rules" element={<RulesPage />} />
        <Route path="companies" element={<CompaniesPage />} />
        {user.role === "admin" && <Route path="team" element={<TeamPage />} />}
        {user.is_platform_admin && <Route path="resellers" element={<ResellersPage />} />}
        {user.is_platform_admin && <Route path="updates" element={<UpdatesPage />} />}
        {user.is_platform_admin && <Route path="backups" element={<BackupsPage />} />}
        {(user.is_platform_admin || user.is_reseller_admin) && <Route path="plans" element={<PlansPage />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
