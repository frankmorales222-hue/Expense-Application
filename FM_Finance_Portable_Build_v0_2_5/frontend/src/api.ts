import type {
  AppSettings, Category, ExpenseDetail, ExpenseFilters, ExpenseInput, ExpensePage, ExpenseStatus,
  Receipt, Summary, User, Vendor,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationIssue[])
        .map((d) => {
          const field = d.loc ? String(d.loc[d.loc.length - 1]).replace(/_/g, " ") : "";
          return field ? `${field}: ${d.msg ?? "invalid"}` : d.msg ?? "invalid";
        })
        .join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/login") window.dispatchEvent(new Event("fm:unauthorized"));
    throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`));
  }
  return data as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  login: (email: string, password: string) => request<User>("/auth/login", { method: "POST", ...json({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/change-password", { method: "POST", ...json({ current_password, new_password }) }),
  settings: () => request<AppSettings>("/settings"),

  categories: (includeInactive = false) => request<Category[]>(`/categories${query({ include_inactive: includeInactive ? "true" : undefined })}`),
  createCategory: (name: string, approval_threshold: number | null) =>
    request<Category>("/categories", { method: "POST", ...json({ name, approval_threshold }) }),
  updateCategory: (id: string, body: Partial<Pick<Category, "name" | "is_active" | "sort_order">> & { approval_threshold?: number; clear_threshold?: boolean }) =>
    request<Category>(`/categories/${id}`, { method: "PUT", ...json(body) }),

  vendors: (q: string) => request<Vendor[]>(`/vendors${query({ q })}`),

  listExpenses: (f: ExpenseFilters, page = 1, pageSize = 25) =>
    request<ExpensePage>(`/expenses${query({ ...f, page, page_size: pageSize })}`),
  exportUrl: (f: ExpenseFilters) => `/api/expenses/export.csv${query({ ...f })}`,
  getExpense: (id: string) => request<ExpenseDetail>(`/expenses/${id}`),
  createExpense: (body: ExpenseInput) => request<ExpenseDetail>("/expenses", { method: "POST", ...json(body) }),
  updateExpense: (id: string, body: ExpenseInput) => request<ExpenseDetail>(`/expenses/${id}`, { method: "PUT", ...json(body) }),
  setStatus: (id: string, status: ExpenseStatus, note?: string) =>
    request<ExpenseDetail>(`/expenses/${id}/status`, { method: "POST", ...json({ status, note }) }),
  deleteExpense: (id: string) => request<void>(`/expenses/${id}`, { method: "DELETE" }),

  uploadReceipt: (expenseId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Receipt>(`/expenses/${expenseId}/receipts`, { method: "POST", body: form });
  },
  receiptUrl: (id: string) => `/api/receipts/${id}/content`,
  deleteReceipt: (id: string) => request<void>(`/receipts/${id}`, { method: "DELETE" }),

  summary: (date_from?: string, date_to?: string) => request<Summary>(`/reports/summary${query({ date_from, date_to })}`),
};
