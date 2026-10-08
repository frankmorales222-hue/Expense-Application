export type ExpenseStatus = "pending" | "approved" | "paid" | "rejected";
export type PaymentMethod = "business_card" | "business_bank" | "personal_card" | "cash" | "other";

export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "approver" | "submitter";
}

export interface AppSettings {
  version: string;
  currency: string;
  approval_required: boolean;
  default_approval_threshold: number;
  max_receipt_mb: number;
}

export interface Category {
  id: string;
  code: string;
  name: string;
  approval_threshold: number | null;
  is_active: boolean;
  sort_order: number;
}

export interface Vendor {
  id: string;
  name: string;
}

export interface ExpenseListItem {
  id: string;
  expense_date: string;
  vendor_name: string | null;
  category_id: string;
  category_name: string;
  description: string;
  amount: number;
  currency: string;
  payment_method: PaymentMethod | null;
  is_reimbursable: boolean;
  status: ExpenseStatus;
  receipt_count: number;
  created_at: string;
}

export interface Receipt {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  user_name: string | null;
  changes: Record<string, unknown> | null;
  created_at: string;
}

export interface ExpenseDetail extends ExpenseListItem {
  notes: string | null;
  approved_at: string | null;
  paid_at: string | null;
  receipts: Receipt[];
  history: AuditEntry[];
  allowed_transitions: ExpenseStatus[];
}

export interface ExpensePage {
  items: ExpenseListItem[];
  total: number;
  total_amount: number;
  page: number;
  page_size: number;
}

export interface ExpenseInput {
  expense_date: string;
  vendor_name: string | null;
  category_id: string;
  description: string;
  amount: number;
  payment_method: PaymentMethod | null;
  is_reimbursable: boolean;
  notes: string | null;
}

export interface NameAmount {
  key: string;
  label: string;
  amount: number;
  count: number;
}

export interface Summary {
  date_from: string | null;
  date_to: string | null;
  total_spent: number;
  expense_count: number;
  pending_count: number;
  pending_amount: number;
  reimbursable_owed: number;
  by_status: NameAmount[];
  by_category: NameAmount[];
  by_month: NameAmount[];
}

export interface ExpenseFilters {
  status?: ExpenseStatus | "";
  category_id?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
  sort?: "date_desc" | "date_asc" | "amount_desc" | "amount_asc";
}
