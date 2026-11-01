import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../context";

/** The current company's logo when it has one; otherwise the default F&M mark.
 *  Signed in: follows the company being worked in. Sign-in page: the company this browser last used. */
export const BRANDING_CHANGED = "fm-branding-changed";

interface Mark { name: string; url: string | null }

export default function BrandMark({ login = false }: { login?: boolean }) {
  const { user } = useAuth();
  const companyId = login ? null : user?.company_id ?? null;
  const [mark, setMark] = useState<Mark | null>(null);
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        if (companyId) {
          const c = await api.company();
          setMark({ name: c.name, url: c.has_logo ? `/api/company/${c.id}/logo?v=${c.logo_version}` : null });
        } else {
          const b = await api.branding();
          setMark({ name: b.name, url: b.has_logo && b.company_id ? `/api/company/${b.company_id}/logo?v=${b.logo_version}` : null });
        }
        setBroken(false);
      } catch {
        setMark(null);
      }
    };
    void load();
    window.addEventListener(BRANDING_CHANGED, load);
    return () => window.removeEventListener(BRANDING_CHANGED, load);
  }, [companyId]);

  if (mark?.url && !broken) {
    return (
      <div className={login ? "brand brand-login brand-has-logo" : "brand brand-has-logo"}>
        <img className="brand-logo" src={mark.url} alt={mark.name} onError={() => setBroken(true)} />
      </div>
    );
  }
  return (
    <div className={login ? "brand brand-login" : "brand"}>
      <span className="brand-mark" aria-hidden="true">FM</span>
      <span className="brand-name">F&amp;M Finance<small>Accounting for small business</small></span>
    </div>
  );
}
