import { Link } from "react-router-dom";
import { useAuth } from "../context";

export default function NoCompanyPage() {
  const { user } = useAuth();
  const canAdd = !!user && (user.is_platform_admin || user.is_reseller_admin);
  return (
    <div className="page">
      <section className="empty">
        <h2>{canAdd ? "Add your first company" : "You don't have access to a company yet"}</h2>
        <p>{canAdd
          ? "Each company gets its own books, bank accounts, categories, logo and team."
          : "Ask the company's owner to add you on their Team page, then sign in again."}</p>
        {canAdd && <Link className="btn btn-primary" to="/companies">Add a company</Link>}
      </section>
    </div>
  );
}
