import { Link } from "react-router-dom";
import { useAuth } from "./context";
import type { ModuleKey, User } from "./types";

export const MODULE_LABEL: Record<ModuleKey, string> = {
  invoicing: "Invoicing", bills: "Bills", smart_capture: "Smart capture", advanced_accounting: "Advanced accounting",
};

/** Is the module switched on for the open company? (Companies from before plans have every module.) */
export function hasModule(user: User | null | undefined, key: ModuleKey): boolean {
  if (!user) return false;
  if (key === "advanced_accounting" && user.company_role === "accountant") return true; // always free for the accountant
  return !user.modules || user.modules.includes(key);
}

/** Show the module's pages: switched on, or switched off but holding records (read-only). */
export function showModule(user: User | null | undefined, key: ModuleKey): boolean {
  return hasModule(user, key) || !!user?.module_data?.includes(key);
}

export function useModule(key: ModuleKey): { on: boolean; visible: boolean } {
  const { user } = useAuth();
  return { on: hasModule(user, key), visible: showModule(user, key) };
}

/** Banner on pages of a module that's switched off: what's here stays readable. */
export function ModuleNotice({ module }: { module: ModuleKey }) {
  const { on } = useModule(module);
  if (on) return null;
  return (
    <div className="module-notice" role="status">
      <strong>{MODULE_LABEL[module]} isn't in your plan.</strong> You can still view, print and export what's here,
      but you can't add or change anything. <Link to="/settings#plan">See your plan</Link>
    </div>
  );
}
