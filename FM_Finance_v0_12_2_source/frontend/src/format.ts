import type { CompanyRules, ExpenseStatus, RulesResponse, Term } from "./types";

// ---------- v0.10.0: the company's own formats and lists ----------
// Loaded once per session (switching company reloads the page). Defaults match earlier versions.

interface Formats {
  currency: string;
  symbol: string | null;
  dateFormat: CompanyRules["date_format"];
  numberFormat: CompanyRules["number_format"];
  symbols: Record<string, string>;
}
let FMT: Formats = { currency: "USD", symbol: null, dateFormat: "MM/DD/YYYY", numberFormat: "1,234.56", symbols: { USD: "$" } };
let RULES: RulesResponse | null = null;

export function setCompanyRules(r: RulesResponse | null): void {
  RULES = r;
  if (!r) return;
  FMT = { currency: r.currency, symbol: r.rules.currency_symbol, dateFormat: r.rules.date_format,
    numberFormat: r.rules.number_format, symbols: r.currency_symbols };
}

export function companyRules(): RulesResponse | null {
  return RULES;
}

const SEPARATORS: Record<CompanyRules["number_format"], [string, string]> = {
  "1,234.56": [",", "."], "1.234,56": [".", ","], "1 234,56": ["\u00a0", ","], "1'234.56": ["'", "."],
};
const places = new Map<string, number>();

function fractionDigits(currency: string): number {
  let p = places.get(currency);
  if (p === undefined) {
    try {
      p = new Intl.NumberFormat("en-US", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
    } catch {
      p = 2;
    }
    places.set(currency, p);
  }
  return p;
}

/** A number in the company's style (1,234.56 / 1.234,56 / ...). */
export function formatNumber(n: number, digits = 2): string {
  const [group, decimal] = SEPARATORS[FMT.numberFormat] ?? [",", "."];
  const [whole, frac] = Math.abs(n).toFixed(digits).split(".");
  const grouped = (whole ?? "0").replace(/\B(?=(\d{3})+(?!\d))/g, group);
  return (n < 0 ? "-" : "") + grouped + (frac ? decimal + frac : "");
}

export function currencySymbol(currency = FMT.currency): string {
  if (currency === FMT.currency && FMT.symbol) return FMT.symbol;
  return FMT.symbols[currency] ?? `${currency} `;
}

/** Money in the company's currency and number style. Without a currency, the company's currency. */
export function money(amount: number, currency?: string): string {
  const cur = currency || FMT.currency;
  const text = formatNumber(Math.abs(amount), fractionDigits(cur));
  return (amount < 0 && Math.abs(amount) >= 0.005 ? "-" : "") + currencySymbol(cur) + text;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A YYYY-MM-DD date in the company's order (readable month names on screen; avoids time-zone day shifts). */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  switch (FMT.dateFormat) {
    case "DD/MM/YYYY":
    case "DD.MM.YYYY":
      return `${d} ${MONTHS[m - 1]} ${y}`;
    case "YYYY-MM-DD":
      return iso.slice(0, 10);
    default:
      return `${MONTHS[m - 1]} ${d}, ${y}`;
  }
}

/** A date exactly as the company writes it on documents (10/01/2026, 01.10.2026...). */
export function formatDateShort(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return iso;
  return FMT.dateFormat.replace("YYYY", y).replace("MM", m).replace("DD", d);
}

/** The company's payment terms (active only, plus the one a record already uses). */
export function termOptions(current?: string | null): Term[] {
  const all = RULES?.rules.terms ?? FALLBACK_TERMS;
  return all.filter((t) => t.active || t.code === current);
}

export function termName(code: string | null | undefined): string {
  if (!code) return "";
  return (RULES?.rules.terms ?? FALLBACK_TERMS).find((t) => t.code === code)?.name ?? code.replace(/_/g, " ");
}

/** Due date for a term, the same way the server works it out. */
export function dueDateFor(code: string | null | undefined, start: string): string {
  const t = (RULES?.rules.terms ?? FALLBACK_TERMS).find((x) => x.code === code);
  if (!t) return start;
  const [y, m] = start.split("-").map(Number) as [number, number, number];
  if (t.kind === "end_of_month") return addDaysISO(toISODate(new Date(y, m, 0)), t.days);
  if (t.kind === "day_of_next_month") {
    const last = new Date(y, m + 1, 0).getDate();
    return toISODate(new Date(y, m, Math.min(t.day ?? 1, last)));
  }
  return addDaysISO(start, t.days);
}

export function defaultTerm(kind: "invoice" | "bill"): string {
  const r = RULES?.rules;
  const wanted = kind === "bill" ? r?.bill_default_terms : r?.default_terms;
  const list = termOptions();
  return (wanted && list.some((t) => t.code === wanted) ? wanted : null)
    ?? (list.some((t) => t.code === "net_30") ? "net_30" : list[0]?.code ?? "net_30");
}

export function methodOptions(kind: "expense" | "received", current?: string | null): { code: string; label: string }[] {
  const list = kind === "expense" ? RULES?.rules.expense_methods : RULES?.rules.received_methods;
  const fallback = kind === "expense" ? PAYMENT_LABEL : PAYMENT_METHOD_IN_LABEL;
  const all = list ?? Object.entries(fallback).map(([code, label]) => ({ code, label, active: true }));
  return all.filter((c) => c.active || c.code === current);
}

export function methodLabel(kind: "expense" | "received", code: string | null | undefined): string {
  if (!code) return "";
  const list = kind === "expense" ? RULES?.rules.expense_methods : RULES?.rules.received_methods;
  const fallback = kind === "expense" ? PAYMENT_LABEL : PAYMENT_METHOD_IN_LABEL;
  return list?.find((c) => c.code === code)?.label ?? fallback[code] ?? code.replace(/_/g, " ");
}

const FALLBACK_TERMS: Term[] = [
  { code: "due_on_receipt", name: "Due on receipt", kind: "days", days: 0, day: null, active: true },
  { code: "net_15", name: "Net 15", kind: "days", days: 15, day: null, active: true },
  { code: "net_30", name: "Net 30", kind: "days", days: 30, day: null, active: true },
  { code: "net_45", name: "Net 45", kind: "days", days: 45, day: null, active: true },
  { code: "net_60", name: "Net 60", kind: "days", days: 60, day: null, active: true },
];

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

/** Local calendar date as YYYY-MM-DD. */
export function toISODate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const today = (): string => toISODate(new Date());

export const STATUS_LABEL: Record<ExpenseStatus, string> = {
  pending: "Pending approval",
  approved: "Approved",
  paid: "Paid",
  rejected: "Rejected",
};

export const STATUS_ACTION: Record<ExpenseStatus, string> = {
  pending: "Resubmit for approval",
  approved: "Approve",
  paid: "Mark as paid",
  rejected: "Reject",
};

/** Built-in labels, used until the company's rules load. Prefer methodLabel(). */
export const PAYMENT_LABEL: Record<string, string> = {
  business_card: "Business card",
  business_bank: "Business bank account",
  personal_card: "Personal card",
  cash: "Cash",
  other: "Other",
};

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export interface DateRange {
  key: string;
  label: string;
  from?: string;
  to?: string;
}

export function presetRanges(now = new Date()): DateRange[] {
  const y = now.getFullYear();
  const m = now.getMonth();
  const q = Math.floor(m / 3) * 3;
  return [
    { key: "month", label: "This month", from: toISODate(new Date(y, m, 1)), to: toISODate(now) },
    { key: "last_month", label: "Last month", from: toISODate(new Date(y, m - 1, 1)), to: toISODate(new Date(y, m, 0)) },
    { key: "quarter", label: "This quarter", from: toISODate(new Date(y, q, 1)), to: toISODate(now) },
    { key: "ytd", label: "Year to date", from: toISODate(new Date(y, 0, 1)), to: toISODate(now) },
    { key: "12m", label: "Last 12 months", from: toISODate(new Date(y, m - 11, 1)), to: toISODate(now) },
    { key: "all", label: "All time" },
  ];
}

export const ACCOUNT_KIND_LABEL: Record<string, string> = {
  checking: "Checking",
  savings: "Savings",
  credit_card: "Credit card",
  cash: "Cash",
  other: "Other",
};

export const CATEGORY_KIND_LABEL: Record<string, string> = {
  expense: "Expense",
  income: "Income",
  equity: "Owner / equity",
};

export function confidenceLevel(c: number): "high" | "medium" | "low" | "none" {
  if (c >= 85) return "high";
  if (c >= 60) return "medium";
  if (c > 0) return "low";
  return "none";
}

export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

export const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  accountant: "Accountant",
  bookkeeper: "Bookkeeper",
  employee: "Employee",
  viewer: "View only",
};

export const ROLE_HELP: Record<string, string> = {
  owner: "Everything, including settings, bank accounts and who has access",
  accountant: "Banking, approving and editing all expenses; no settings or team",
  bookkeeper: "Banking, approving and editing all expenses; no settings or team",
  employee: "Adds and sees only their own expenses",
  viewer: "Sees everything, changes nothing",
};

// ---------- v0.7.0 sales ----------
export function addDaysISO(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return toISODate(new Date(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
}

export const INVOICE_STATUS_LABEL: Record<string, string> = {
  not_sent: "Not sent", sent: "Sent", partial: "Partly paid", paid: "Paid", overdue: "Overdue", void: "Void",
};

export const PAYMENT_METHOD_IN_LABEL: Record<string, string> = {
  ach: "ACH / bank transfer", check: "Check", card: "Credit card", cash: "Cash", wire: "Wire", other: "Other",
};

/** Days past the due date (0 or less means not late yet). */
export function daysLate(due: string, on: string = today()): number {
  const a = new Date(`${due}T00:00:00`);
  const b = new Date(`${on}T00:00:00`);
  return Math.round((b.getTime() - a.getTime()) / 86400000);
}
