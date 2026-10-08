import type { ExpenseStatus, PaymentMethod } from "./types";

const moneyFormatters = new Map<string, Intl.NumberFormat>();

export function money(amount: number, currency = "USD"): string {
  let f = moneyFormatters.get(currency);
  if (!f) {
    f = new Intl.NumberFormat("en-US", { style: "currency", currency });
    moneyFormatters.set(currency, f);
  }
  return f.format(amount);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Format a YYYY-MM-DD string without going through Date (avoids time-zone day shifts). */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

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

export const PAYMENT_LABEL: Record<PaymentMethod, string> = {
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
