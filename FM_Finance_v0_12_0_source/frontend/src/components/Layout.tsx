import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api";
import BrandMark from "./BrandMark";
import Icon, { type IconName } from "./Icon";
import CompanySwitcher from "./CompanySwitcher";
import { useAuth, useToast } from "../context";
import { showModule } from "../modules";
import type { ModuleKey, User } from "../types";

interface NavItem { to: string; label: string; icon: IconName; end: boolean; show: (u: User) => boolean }

const mod = (key: ModuleKey, base: (u: User) => boolean) => (u: User) => base(u) && showModule(u, key);

// v0.10.0: a company role can take areas away (permissions[area] === "none"); the server enforces the same map.
const area = (key: string, base: (u: User) => boolean) => (u: User) => base(u) && (u.permissions?.[key] ?? "full") !== "none";
const inCompany = (u: User) => u.role !== "none";
const canBank = area("banking", (u: User) => u.role === "admin" || u.role === "approver" || u.role === "viewer");
const books = (u: User) => u.role === "admin" || u.role === "approver";
const sales = area("sales", books);
const bills = area("bills", books);
const reports = area("reports", books);
const accounting = area("accounting", books);
const NAV: { section: string | null; items: NavItem[] }[] = [
  { section: null, items: [
    { to: "/", label: "Dashboard", icon: "home", end: true, show: inCompany },
    { to: "/banking", label: "Banking", icon: "bank", end: false, show: canBank },
  ] },
  { section: "Sales", items: [
    { to: "/invoices", label: "Invoices", icon: "invoice", end: false, show: mod("invoicing", sales) },
    { to: "/customers", label: "Customers", icon: "users", end: false, show: sales },
    { to: "/products", label: "Products and services", icon: "box", end: true, show: mod("invoicing", sales) },
  ] },
  { section: "Expenses", items: [
    { to: "/expenses", label: "Expenses", icon: "receipt", end: true, show: area("expenses", inCompany) },
    { to: "/expenses/new", label: "Add expense", icon: "plusDoc", end: true,
      show: (u) => inCompany(u) && u.role !== "viewer" && (u.permissions?.expenses ?? "full") === "full" },
    { to: "/bills", label: "Bills", icon: "calendar", end: false, show: mod("bills", bills) },
  ] },
  { section: "Accounting", items: [
    { to: "/accounts", label: "Accounts", icon: "wallet", end: true, show: canBank },
    { to: "/reports", label: "Reports", icon: "chart", end: true, show: reports },
    { to: "/chart-of-accounts", label: "Chart of accounts", icon: "book", end: false, show: accounting },
    { to: "/journal", label: "Journal entries", icon: "journal", end: false, show: mod("advanced_accounting", accounting) },
    { to: "/owner-funds", label: "Owner funds", icon: "wallet", end: true, show: accounting },
    { to: "/reconcile", label: "Reconcile", icon: "check", end: false, show: accounting },
    { to: "/accountant", label: "Accountant center", icon: "book", end: true, show: accounting },
  ] },
  { section: null, items: [
    { to: "/team", label: "Team", icon: "team", end: true, show: area("team", (u) => u.role === "admin") },
    { to: "/settings", label: "Settings", icon: "settings", end: true, show: inCompany },
  ] },
];
const ADMIN_NAV: NavItem[] = [
  { to: "/companies", label: "Companies", icon: "building", end: true,
    show: (u) => u.company_count > 1 || u.is_platform_admin || u.is_reseller_admin },
  { to: "/plans", label: "Plans and modules", icon: "layers", end: true, show: (u) => u.is_platform_admin || u.is_reseller_admin },
  { to: "/resellers", label: "Resellers", icon: "store", end: true, show: (u) => u.is_platform_admin },
  { to: "/updates", label: "Updates", icon: "upload", end: true, show: (u) => u.is_platform_admin },
  { to: "/backups", label: "Backups", icon: "book", end: true, show: (u) => u.is_platform_admin },
];

export default function Layout() {
  const { user, settings, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [stopped, setStopped] = useState(false);

  async function signOut() {
    await logout();
    navigate("/login", { replace: true });
  }

  async function exitApp() {
    if (!window.confirm("Stop F&M Finance? You'll need to start FMFinance.exe again to use it.")) return;
    try {
      await api.shutdown();
      setStopped(true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not stop the app");
    }
  }

  if (stopped) {
    return (
      <div className="login">
        <div className="login-card">
          <h1>F&amp;M Finance has stopped</h1>
          <p className="muted">Your data is saved. You can close this tab. Start FMFinance.exe to open it again.</p>
        </div>
      </div>
    );
  }
  if (!user) return null;
  const adminLinks = ADMIN_NAV.filter((n) => n.show(user));

  return (
    <div className="shell">
      <aside className="sidebar">
        <BrandMark />
        <CompanySwitcher />
        <nav aria-label="Main">
          {NAV.map((group, gi) => {
            const items = group.items.filter((n) => n.show(user));
            if (items.length === 0) return null;
            return (
              <div key={gi} className="nav-group">
                {group.section && items.length > 1 && <div className="nav-section">{group.section}</div>}
                {items.map((n) => (
                  <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                    <Icon name={n.icon} />{n.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
          {adminLinks.length > 0 && <div className="nav-section">Administration</div>}
          {adminLinks.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              <Icon name={n.icon} />{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="who"><span className="avatar" aria-hidden="true">{initials(user.name)}</span>
            <span>{user.name}<small>{roleLabel(user)}</small></span></div>
          <div className="foot-links">
            <button type="button" className="link-button" onClick={() => void signOut()}>Sign out</button>
            {settings?.desktop_mode && user.role === "admin" && (
              <button type="button" className="link-button danger" onClick={() => void exitApp()}>Exit app</button>
            )}
          </div>
          {settings && <div className="version">v{settings.version}{settings.database === "sqlite" ? " (test database)" : ""}</div>}
        </div>
      </aside>
      <main className="main">
        {user.role === "viewer" && (
          <div className="viewonly-banner" role="status">You have view-only access to {user.company_name}.</div>
        )}
        <Outlet />
      </main>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

const ROLE_LABEL: Record<string, string> = {
  owner: "Owner", accountant: "Accountant", bookkeeper: "Bookkeeper", employee: "Employee", viewer: "View only",
};

function roleLabel(u: User): string {
  if (u.custom_role_name) return u.custom_role_name;
  const label = u.company_role ? ROLE_LABEL[u.company_role] : undefined;
  if (label) return label;
  if (u.is_platform_admin) return "Platform administrator";
  if (u.is_reseller_admin) return "Reseller administrator";
  return "";
}
