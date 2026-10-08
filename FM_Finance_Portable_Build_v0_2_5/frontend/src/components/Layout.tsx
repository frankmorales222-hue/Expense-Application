import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/expenses", label: "Expenses", end: true },
  { to: "/expenses/new", label: "Add expense", end: true },
  { to: "/settings", label: "Settings", end: true },
];

export default function Layout() {
  const { user, settings, logout } = useAuth();
  const navigate = useNavigate();

  async function signOut() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">F&amp;M</span>
          <span className="brand-name">Finance</span>
        </div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="who">{user?.name}</div>
          <button type="button" className="link-button" onClick={() => void signOut()}>Sign out</button>
          {settings && <div className="version">v{settings.version}</div>}
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
