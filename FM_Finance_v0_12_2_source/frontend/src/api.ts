import type {
  Account, AccountInput, AppSettings, BalanceSheet, BillDetail, BillInput, BillPage, BooksStatus, JournalEntry,
  JournalLineInput, LedgerAccount, LedgerAccountInput, PeerTxn, ProfitLoss, Register, TrialBalance, BillCapabilities, BillExtract, Branding, CompanyListItem, CompanyRole, Member,
  Reseller, ResellerAdmin, BulkResult, Candidates, Category, CategoryKind, Company, CsvMapping,
  Customer, ExpenseDetail, ExpenseFilters, ExpenseInput, ExpensePage, ExpenseStatus, ImportBatch, ImportPreview,
  ManualTxnInput, Receipt, Summary, Txn, TxnFilters, TxnPage, TxnUpdate, User, Vendor,
  Aging, Billable, CustomerDetail, CustomerInput, EmailDraft, EmailSettings, EmailSettingsInput, InvoiceDetail,
  InvoiceInput, InvoicePage, Item, ItemInput, MicrosoftStart, CompanyPlan, ModuleKey, PlanKey, PlansCatalog, PaymentInput, PaymentOut, SalesByCustomer, SalesSummary,
  Dashboard, BankRule, BankRuleInput, CompanyRules, CustomRole, PlanEditInput, PlanInfo, RoleAreas, RoleInput,
  AuditLogPage, BackupStatus, OwnerFunds, OwnerFundsAction, Reconciliation, ReconciliationSummary,
  RulesResponse, UpdateStatus,
} from "./types";
import type { Theme } from "./theme";

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
  // The Windows desktop UI is a browser window. These calls let the local server
  // stop after the final window closes while allowing an ordinary refresh to reconnect.
  desktopUiOpen: (clientId: string) =>
    request<void>(`/system/ui/open?client_id=${encodeURIComponent(clientId)}`, { method: "POST" }),
  desktopUiClose: (clientId: string) => {
    const url = `/api/system/ui/close?client_id=${encodeURIComponent(clientId)}`;
    if (navigator.sendBeacon?.(url)) return;
    void fetch(url, { method: "POST", credentials: "same-origin", keepalive: true });
  },
  login: (email: string, password: string) => request<User>("/auth/login", { method: "POST", ...json({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/change-password", { method: "POST", ...json({ current_password, new_password }) }),
  settings: () => request<AppSettings>("/settings"),

  categories: (includeInactive = false) => request<Category[]>(`/categories${query({ include_inactive: includeInactive ? "true" : undefined })}`),
  createCategory: (name: string, approval_threshold: number | null, kind: CategoryKind = "expense") =>
    request<Category>("/categories", { method: "POST", ...json({ name, approval_threshold, kind }) }),
  updateCategory: (id: string, body: Partial<Pick<Category, "name" | "is_active" | "sort_order" | "kind" | "tax_line">> & { approval_threshold?: number; clear_threshold?: boolean }) =>
    request<Category>(`/categories/${id}`, { method: "PUT", ...json(body) }),

  vendors: (q: string) => request<Vendor[]>(`/vendors${query({ q })}`),

  listExpenses: (f: ExpenseFilters, page = 1, pageSize = 25) =>
    request<ExpensePage>(`/expenses${query({ ...f, page, page_size: pageSize })}`),
  exportUrl: (f: ExpenseFilters) => `/api/expenses/export.csv${query({ ...f })}`,
  getExpense: (id: string) => request<ExpenseDetail>(`/expenses/${id}`),
  createExpense: (body: ExpenseInput) => request<ExpenseDetail>("/expenses", { method: "POST", ...json(body) }),
  updateExpense: (id: string, body: ExpenseInput) => request<ExpenseDetail>(`/expenses/${id}`, { method: "PUT", ...json(body) }),
  setStatus: (id: string, status: ExpenseStatus, note?: string, payment_account_id?: string) =>
    request<ExpenseDetail>(`/expenses/${id}/status`, { method: "POST", ...json({ status, note, payment_account_id }) }),
  deleteExpense: (id: string) => request<void>(`/expenses/${id}`, { method: "DELETE" }),

  uploadReceipt: (expenseId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Receipt>(`/expenses/${expenseId}/receipts`, { method: "POST", body: form });
  },
  receiptUrl: (id: string) => `/api/receipts/${id}/content`,
  deleteReceipt: (id: string) => request<void>(`/receipts/${id}`, { method: "DELETE" }),

  summary: (date_from?: string, date_to?: string) => request<Summary>(`/reports/summary${query({ date_from, date_to })}`),

  // ---------- bills ----------
  bills: (show: "unpaid" | "paid" | "all", search?: string) => request<BillPage>(`/bills${query({ show, search })}`),
  getBill: (id: string) => request<BillDetail>(`/bills/${id}`),
  createBill: (body: BillInput) => request<BillDetail>("/bills", { method: "POST", ...json(body) }),
  updateBill: (id: string, body: BillInput) => request<BillDetail>(`/bills/${id}`, { method: "PUT", ...json(body) }),
  deleteBill: (id: string) => request<void>(`/bills/${id}`, { method: "DELETE" }),
  billPaymentCandidates: (id: string, account_id: string, amount: number, payment_date: string) =>
    request<PeerTxn[]>(`/bills/${id}/payment-candidates${query({ account_id, amount, payment_date })}`),
  payBill: (id: string, body: { payment_date: string; account_id: string; amount: number; memo: string | null;
    transaction_id: string | null }) => request<BillDetail>(`/bills/${id}/payments`, { method: "POST", ...json(body) }),
  deleteBillPayment: (id: string, paymentId: string) =>
    request<BillDetail>(`/bills/${id}/payments/${paymentId}`, { method: "DELETE" }),
  uploadBillAttachment: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<unknown>(`/bills/${id}/attachments`, { method: "POST", body: form });
  },
  billAttachmentUrl: (id: string, attId: string) => `/api/bills/${id}/attachments/${attId}/content`,
  deleteBillAttachment: (id: string, attId: string) =>
    request<void>(`/bills/${id}/attachments/${attId}`, { method: "DELETE" }),

  // ---------- sales ----------
  items: (includeInactive = false) =>
    request<Item[]>(`/items${query({ include_inactive: includeInactive ? "true" : undefined })}`),
  createItem: (body: ItemInput) => request<Item>("/items", { method: "POST", ...json(body) }),
  updateItem: (id: string, body: ItemInput) => request<Item>(`/items/${id}`, { method: "PUT", ...json(body) }),
  invoices: (show: "unpaid" | "paid" | "all", search?: string, customer_id?: string) =>
    request<InvoicePage>(`/invoices${query({ show, search, customer_id })}`),
  nextInvoiceNumber: () => request<{ invoice_number: string }>("/invoices/next-number"),
  billable: (customer_id: string, invoice_id?: string) =>
    request<Billable[]>(`/invoices/billable${query({ customer_id, invoice_id })}`),
  getInvoice: (id: string) => request<InvoiceDetail>(`/invoices/${id}`),
  createInvoice: (body: InvoiceInput) => request<InvoiceDetail>("/invoices", { method: "POST", ...json(body) }),
  updateInvoice: (id: string, body: InvoiceInput) =>
    request<InvoiceDetail>(`/invoices/${id}`, { method: "PUT", ...json(body) }),
  deleteInvoice: (id: string) => request<void>(`/invoices/${id}`, { method: "DELETE" }),
  voidInvoice: (id: string) => request<InvoiceDetail>(`/invoices/${id}/void`, { method: "POST" }),
  markSent: (id: string, sent: boolean) =>
    request<InvoiceDetail>(`/invoices/${id}/mark-sent${query({ sent: sent ? "true" : "false" })}`, { method: "POST" }),
  invoicePdfUrl: (id: string, download = false) => `/api/invoices/${id}/pdf${download ? "?download=true" : ""}`,
  emailDraft: (id: string) => request<EmailDraft>(`/invoices/${id}/email-draft`),
  sendInvoice: (id: string, body: { to: string[]; cc: string[]; subject: string; body: string }) =>
    request<InvoiceDetail>(`/invoices/${id}/send`, { method: "POST", ...json(body) }),
  payments: (customer_id?: string) => request<PaymentOut[]>(`/payments${query({ customer_id })}`),
  depositCandidates: (account_id: string, amount: number, payment_date: string) =>
    request<PeerTxn[]>(`/payments/deposit-candidates${query({ account_id, amount, payment_date })}`),
  receivePayment: (body: PaymentInput) => request<PaymentOut>("/payments", { method: "POST", ...json(body) }),
  deletePayment: (id: string) => request<void>(`/payments/${id}`, { method: "DELETE" }),
  customerDetail: (id: string) => request<CustomerDetail>(`/customers/${id}`),
  salesSummary: () => request<SalesSummary>("/sales/summary"),
  aging: (as_of: string) => request<Aging>(`/sales/aging${query({ as_of })}`),
  salesByCustomer: (date_from: string, date_to: string) =>
    request<SalesByCustomer>(`/sales/by-customer${query({ date_from, date_to })}`),
  emailSettings: () => request<EmailSettings>("/email-settings"),
  saveEmailSettings: (body: EmailSettingsInput) =>
    request<EmailSettings>("/email-settings", { method: "PUT", ...json(body) }),
  removeEmailSettings: () => request<void>("/email-settings", { method: "DELETE" }),
  msStart: (client_id: string | null, tenant_id: string | null) =>
    request<MicrosoftStart>("/email-settings/microsoft/start", { method: "POST", ...json({ client_id, tenant_id }) }),
  msPoll: (flow_id: string) =>
    request<{ status: "pending" | "connected"; settings: EmailSettings | null }>("/email-settings/microsoft/poll",
      { method: "POST", ...json({ flow_id }) }),
  msDisconnect: () => request<EmailSettings>("/email-settings/microsoft/disconnect", { method: "POST" }),
  saveEmailOptions: (body: { reply_to: string | null; copy_me: boolean }) =>
    request<EmailSettings>("/email-settings/options", { method: "PUT", ...json(body) }),
  testEmail: (to: string) => request<{ sent: boolean }>("/email-settings/test", { method: "POST", ...json({ to }) }),

  // ---------- the books ----------
  ledgerAccounts: (includeInactive = false) =>
    request<LedgerAccount[]>(`/ledger/accounts${query({ include_inactive: includeInactive ? "true" : undefined })}`),
  createLedgerAccount: (body: LedgerAccountInput) =>
    request<LedgerAccount>("/ledger/accounts", { method: "POST", ...json(body) }),
  updateLedgerAccount: (id: string, body: LedgerAccountInput) =>
    request<LedgerAccount>(`/ledger/accounts/${id}`, { method: "PUT", ...json(body) }),
  register: (id: string, date_from?: string, date_to?: string) =>
    request<Register>(`/ledger/accounts/${id}/register${query({ date_from, date_to })}`),
  journal: (source: "manual" | "all") => request<JournalEntry[]>(`/ledger/journal${query({ source })}`),
  getJournal: (id: string) => request<JournalEntry>(`/ledger/journal/${id}`),
  createJournal: (body: { entry_date: string; number: string | null; memo: string | null; lines: JournalLineInput[] }) =>
    request<JournalEntry>("/ledger/journal", { method: "POST", ...json(body) }),
  updateJournal: (id: string, body: { entry_date: string; number: string | null; memo: string | null; lines: JournalLineInput[] }) =>
    request<JournalEntry>(`/ledger/journal/${id}`, { method: "PUT", ...json(body) }),
  deleteJournal: (id: string) => request<void>(`/ledger/journal/${id}`, { method: "DELETE" }),
  profitLoss: (date_from: string, date_to: string) =>
    request<ProfitLoss>(`/ledger/reports/profit-and-loss${query({ date_from, date_to })}`),
  balanceSheet: (as_of: string) => request<BalanceSheet>(`/ledger/reports/balance-sheet${query({ as_of })}`),
  trialBalance: (as_of: string) => request<TrialBalance>(`/ledger/reports/trial-balance${query({ as_of })}`),
  booksStatus: () => request<BooksStatus>("/ledger/status"),
  setClosingDate: (closing_date: string | null) =>
    request<BooksStatus>("/ledger/closing-date", { method: "PUT", ...json({ closing_date }) }),
  ownerFunds: () => request<OwnerFunds>("/owner-funds"),
  recordOwnerFunds: (body: { action: OwnerFundsAction; entry_date: string; amount: number;
    account_id: string | null; transaction_id: string | null; memo: string | null }) =>
    request<OwnerFunds>("/owner-funds", { method: "POST", ...json(body) }),

  // ---------- companies, team, resellers ----------
  companies: () => request<CompanyListItem[]>("/companies"),
  switchCompany: (id: string) => request<User>(`/companies/${id}/switch`, { method: "POST" }),
  plansCatalog: (includeInactive = false) =>
    request<PlansCatalog>(`/plans/catalog${includeInactive ? "?include_inactive=true" : ""}`),
  createPlan: (body: PlanEditInput) => request<PlanInfo>("/plans/catalog", { method: "POST", ...json(body) }),
  editPlan: (id: string, body: PlanEditInput, applyToCompanies: boolean) =>
    request<PlanInfo>(`/plans/catalog/${id}?apply_to_companies=${applyToCompanies}`, { method: "PUT", ...json(body) }),
  companyPlans: () => request<CompanyPlan[]>("/plans/companies"),
  setCompanyPlan: (id: string, body: { plan: PlanKey | "custom"; modules?: ModuleKey[]; user_limit?: number | null }) =>
    request<CompanyPlan>(`/plans/companies/${id}`, { method: "PUT", ...json(body) }),
  setCompanyTheme: (id: string, default_theme: Theme) =>
    request<CompanyPlan>(`/plans/companies/${id}/theme`, { method: "PUT", ...json({ default_theme }) }),
  setMyTheme: (theme: Theme | null) => request<User>("/auth/me/theme", { method: "PUT", ...json({ theme }) }),
  dashboard: () => request<Dashboard>("/dashboard/overview"),
  createCompany: (body: { name: string; legal_name: string | null; reseller_id: string | null; plan?: PlanKey }) =>
    request<CompanyListItem>("/companies", { method: "POST", ...json(body) }),
  members: () => request<Member[]>("/members"),
  addMember: (body: { email: string; name: string | null; role: CompanyRole; custom_role_id?: string | null }) =>
    request<{ member: Member; temporary_password: string | null }>("/members", { method: "POST", ...json(body) }),
  changeMemberRole: (userId: string, role: CompanyRole, custom_role_id: string | null = null) =>
    request<Member>(`/members/${userId}`, { method: "PUT", ...json({ role, custom_role_id }) }),
  removeMember: (userId: string) => request<void>(`/members/${userId}`, { method: "DELETE" }),
  resellers: () => request<Reseller[]>("/resellers"),
  createReseller: (name: string) => request<Reseller>("/resellers", { method: "POST", ...json({ name, is_active: true }) }),
  updateReseller: (id: string, name: string, is_active: boolean) =>
    request<Reseller>(`/resellers/${id}`, { method: "PUT", ...json({ name, is_active }) }),
  addResellerAdmin: (id: string, email: string, name: string | null) =>
    request<{ admin: ResellerAdmin; temporary_password: string | null }>(`/resellers/${id}/admins`,
      { method: "POST", ...json({ email, name }) }),
  removeResellerAdmin: (id: string, userId: string) =>
    request<void>(`/resellers/${id}/admins/${userId}`, { method: "DELETE" }),

  // ---------- bill import ----------
  billCapabilities: () => request<BillCapabilities>("/documents/capabilities"),
  extractBill: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BillExtract>("/documents/extract", { method: "POST", body: form });
  },

  // ---------- banking ----------
  shutdown: () => request<void>("/system/shutdown", { method: "POST" }),
  company: () => request<Company>("/company"),
  branding: () => request<Branding>("/company/branding"),
  uploadLogo: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Company>("/company/logo", { method: "PUT", body: form });
  },
  removeLogo: () => request<Company>("/company/logo", { method: "DELETE" }),
  updateCompany: (body: Pick<Company, "name" | "legal_name" | "fiscal_year_start_month">
    & Partial<Pick<Company, "address" | "phone" | "email" | "website" | "invoice_footer">>) =>
    request<Company>("/company", { method: "PUT", ...json(body) }),

  accounts: (includeInactive = false) =>
    request<Account[]>(`/accounts${query({ include_inactive: includeInactive ? "true" : undefined })}`),
  createAccount: (body: AccountInput) => request<Account>("/accounts", { method: "POST", ...json(body) }),
  updateAccount: (id: string, body: AccountInput) => request<Account>(`/accounts/${id}`, { method: "PUT", ...json(body) }),
  forgetCsvProfile: (id: string) => request<void>(`/accounts/${id}/csv-profile`, { method: "DELETE" }),

  customers: (includeInactive = false) =>
    request<Customer[]>(`/customers${query({ include_inactive: includeInactive ? "true" : undefined })}`),
  createCustomer: (body: CustomerInput) => request<Customer>("/customers", { method: "POST", ...json(body) }),
  updateCustomer: (id: string, body: Partial<CustomerInput> & { name: string }) =>
    request<Customer>(`/customers/${id}`, { method: "PUT", ...json(body) }),

  previewImport: (accountId: string, file: File, mapping?: CsvMapping | null) => {
    const form = new FormData();
    form.append("account_id", accountId);
    if (mapping) form.append("mapping", JSON.stringify(mapping));
    form.append("file", file);
    return request<ImportPreview>("/imports/preview", { method: "POST", body: form });
  },
  commitImport: (accountId: string, file: File, mapping?: CsvMapping | null) => {
    const form = new FormData();
    form.append("account_id", accountId);
    if (mapping) form.append("mapping", JSON.stringify(mapping));
    form.append("file", file);
    return request<ImportBatch>("/imports", { method: "POST", body: form });
  },
  imports: (accountId?: string) => request<ImportBatch[]>(`/imports${query({ account_id: accountId })}`),
  undoImport: (id: string) => request<ImportBatch>(`/imports/${id}/undo`, { method: "POST" }),

  transactions: (f: TxnFilters, page = 1, pageSize = 50) =>
    request<TxnPage>(`/transactions${query({ ...f, page, page_size: pageSize })}`),
  createTransaction: (body: ManualTxnInput) => request<Txn>("/transactions", { method: "POST", ...json(body) }),
  updateTransaction: (id: string, body: TxnUpdate) =>
    request<Txn>(`/transactions/${id}`, { method: "PATCH", ...json(body) }),
  approveTransaction: (id: string) => request<Txn>(`/transactions/${id}/approve`, { method: "POST" }),
  bulkApprove: (ids: string[]) => request<BulkResult>("/transactions/bulk-approve", { method: "POST", ...json({ ids }) }),
  approveConfident: (min_confidence: number, account_id?: string) =>
    request<BulkResult>("/transactions/approve-confident", { method: "POST", ...json({ min_confidence, account_id: account_id || null }) }),
  excludeTransaction: (id: string) => request<Txn>(`/transactions/${id}/exclude`, { method: "POST" }),
  restoreTransaction: (id: string) => request<Txn>(`/transactions/${id}/restore`, { method: "POST" }),
  notDuplicate: (id: string) => request<Txn>(`/transactions/${id}/not-duplicate`, { method: "POST" }),
  candidates: (id: string) => request<Candidates>(`/transactions/${id}/candidates`),
  linkTransfer: (id: string, peer_id: string) =>
    request<Txn>(`/transactions/${id}/link-transfer`, { method: "POST", ...json({ peer_id }) }),
  unlinkTransfer: (id: string) => request<Txn>(`/transactions/${id}/unlink-transfer`, { method: "POST" }),
  createExpenseFromTxn: (id: string) => request<ExpenseDetail>(`/transactions/${id}/create-expense`, { method: "POST" }),

  // v0.12.0 statement reconciliation and accountant review
  reconciliations: (accountId?: string) =>
    request<ReconciliationSummary[]>(`/reconciliations${query({ account_id: accountId })}`),
  getReconciliation: (id: string) => request<Reconciliation>(`/reconciliations/${id}`),
  startReconciliation: (body: { account_id: string; statement_date: string; ending_balance: number; notes: string | null }) =>
    request<Reconciliation>("/reconciliations", { method: "POST", ...json(body) }),
  saveReconciliationSelection: (id: string, transaction_ids: string[]) =>
    request<Reconciliation>(`/reconciliations/${id}/selection`, { method: "PUT", ...json({ transaction_ids }) }),
  completeReconciliation: (id: string) =>
    request<Reconciliation>(`/reconciliations/${id}/complete`, { method: "POST" }),
  cancelReconciliation: (id: string) => request<void>(`/reconciliations/${id}`, { method: "DELETE" }),
  uploadReconciliationStatement: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Reconciliation>(`/reconciliations/${id}/statement`, { method: "POST", body: form });
  },
  reconciliationStatementUrl: (id: string) => `/api/reconciliations/${id}/statement`,
  audit: (filters: { entity_type?: string; action?: string; date_from?: string; date_to?: string }, page = 1, pageSize = 50) =>
    request<AuditLogPage>(`/audit${query({ ...filters, page, page_size: pageSize })}`),
  accountantExportUrl: (dateFrom: string, dateTo: string) =>
    `/api/accountant/export${query({ date_from: dateFrom, date_to: dateTo })}`,

  // v0.10.0 company rules, bank rules and custom roles
  rules: () => request<RulesResponse>("/rules"),
  saveRules: (rules: Partial<CompanyRules>, currency?: string) =>
    request<RulesResponse>("/rules", { method: "PUT", ...json({ rules, currency: currency ?? null }) }),
  bankRules: () => request<BankRule[]>("/bank-rules"),
  createBankRule: (body: BankRuleInput) => request<BankRule>("/bank-rules", { method: "POST", ...json(body) }),
  updateBankRule: (id: string, body: BankRuleInput) =>
    request<BankRule>(`/bank-rules/${id}`, { method: "PUT", ...json(body) }),
  deleteBankRule: (id: string) => request<void>(`/bank-rules/${id}`, { method: "DELETE" }),
  applyBankRules: () => request<{ matched: number; approved: number }>("/bank-rules/apply", { method: "POST" }),
  roleAreas: () => request<RoleAreas>("/roles/areas"),
  roles: () => request<CustomRole[]>("/roles"),
  createRole: (body: RoleInput) => request<CustomRole>("/roles", { method: "POST", ...json(body) }),
  updateRole: (id: string, body: RoleInput) => request<CustomRole>(`/roles/${id}`, { method: "PUT", ...json(body) }),
  deleteRole: (id: string) => request<void>(`/roles/${id}`, { method: "DELETE" }),
  // v0.10.1 updates
  updateStatus: () => request<UpdateStatus>("/updates"),
  uploadUpdate: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UpdateStatus>("/updates/upload", { method: "POST", body: form });
  },
  discardUpdate: () => request<UpdateStatus>("/updates/staged", { method: "DELETE" }),
  applyUpdate: () => request<{ version: string; backup: string }>("/updates/apply", { method: "POST" }),
  // v0.11.0 full database, settings and receipt backups
  backupStatus: () => request<BackupStatus>("/backups"),
  createBackup: () => request<BackupStatus>("/backups", { method: "POST" }),
  restoreBackup: (name: string, restore_settings = true) =>
    request<{ backup: string; version: string; recovery_backup: string }>(
      `/backups/${encodeURIComponent(name)}/restore`, { method: "POST", ...json({ restore_settings }) }),
};

/** "fm-finance:<version>:ok" while the app is up; null while it's restarting. */
export async function probeVersion(): Promise<string | null> {
  try {
    const r = await fetch("/api/health/version", { cache: "no-store" });
    if (!r.ok) return null;
    const m = /^fm-finance:([0-9.]+):ok$/.exec((await r.text()).trim());
    return m?.[1] ?? null;
  } catch {
    return null;
  }
}
