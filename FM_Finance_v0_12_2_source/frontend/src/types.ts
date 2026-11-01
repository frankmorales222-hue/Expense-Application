export type ExpenseStatus = "pending" | "approved" | "paid" | "rejected";
/** A payment-method code from the company's rules (v0.10.0: each company keeps its own list). */
export type PaymentMethod = string;

export type CompanyRole = "owner" | "accountant" | "bookkeeper" | "employee" | "viewer";

export interface User {
  id: string;
  email: string;
  name: string;
  /** Permission in the current company; "none" when the user has no company yet. */
  role: "admin" | "approver" | "submitter" | "viewer" | "none";
  company_role: CompanyRole | null;
  company_id: string | null;
  company_name: string | null;
  company_count: number;
  is_platform_admin: boolean;
  is_reseller_admin: boolean;
  plan?: string | null;
  plan_label?: string | null;
  modules?: ModuleKey[];
  module_data?: ModuleKey[];
  user_limit?: number | null;
  seats_used?: number;
  theme?: "classic" | "executive" | "dark" | null;
  theme_effective?: "classic" | "executive" | "dark";
  company_default_theme?: "classic" | "executive" | "dark";
  /** v0.10.0: what this person can do in each area (full, view or none); follows a custom role when set. */
  permissions?: Record<string, AreaLevel>;
  custom_role_name?: string | null;
}

export type AreaLevel = "full" | "view" | "none";

export type ModuleKey = "invoicing" | "bills" | "smart_capture" | "advanced_accounting";
export type PlanKey = string;

export interface PlansCatalog {
  modules: { key: ModuleKey; label: string; description: string }[];
  plans: PlanInfo[];
}

export interface PlanInfo {
  id: string | null;
  key: PlanKey;
  label: string;
  modules: ModuleKey[];
  user_limit: number | null;
  description: string | null;
  monthly_price: number | null;
  is_active: boolean;
  sort_order: number;
  reseller_id: string | null;
  reseller_name: string | null;
  editable: boolean;
}

export interface PlanEditInput {
  key?: string;
  label: string;
  description: string | null;
  modules: ModuleKey[];
  user_limit: number | null;
  monthly_price: number | null;
  is_active: boolean;
  sort_order: number;
  reseller_id?: string | null;
}

export interface CompanyPlan {
  id: string;
  name: string;
  reseller_name: string | null;
  is_active: boolean;
  plan: string | null;
  plan_label: string;
  modules: ModuleKey[];
  user_limit: number | null;
  seats_used: number;
  created_at: string;
  default_theme: "classic" | "executive" | "dark";
}

export interface AppSettings {
  version: string;
  currency: string;
  approval_required: boolean;
  default_approval_threshold: number;
  max_receipt_mb: number;
  desktop_mode: boolean;
  receipt_storage: "local" | "minio";
  database: "sqlite" | "postgresql";
}

export interface Category {
  id: string;
  code: string;
  name: string;
  approval_threshold: number | null;
  is_active: boolean;
  sort_order: number;
  kind: CategoryKind;
  tax_line: string | null;
}

export type CategoryKind = "expense" | "income" | "equity";

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
  payment_account_id: string | null;
  payment_account_name: string | null;
  line_count: number;
}

export interface LineInput {
  category_id: string;
  description: string | null;
  amount: number;
  billable: boolean;
  customer_id: string | null;
}

export interface LineOut extends LineInput {
  id: string;
  category_name: string;
  customer_name: string | null;
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
  custom?: CustomValues | null;
  lines: LineOut[];
  notes: string | null;
  invoice_number: string | null;
  due_date: string | null;
  bank_transaction_id: string | null;
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
  custom?: CustomValues | null;
  expense_date: string;
  vendor_name: string | null;
  description: string;
  lines: LineInput[];
  payment_account_id: string | null;
  payment_method: PaymentMethod | null;
  is_reimbursable: boolean;
  notes: string | null;
  invoice_number: string | null;
  due_date: string | null;
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

// ---------- Phase 1: banking ----------
export type AccountKind = "checking" | "savings" | "credit_card" | "cash" | "other";
export type ReviewStatus = "unreviewed" | "approved" | "excluded";
export type Tab = "review" | "approved" | "excluded" | "all";
export type TxnFlag = "transfer" | "duplicate" | "uncategorized" | "missing_receipt" | "money_in" | "money_out";

export interface Company {
  id: string;
  name: string;
  legal_name: string | null;
  base_currency: string;
  fiscal_year_start_month: number;
  address: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  invoice_footer: string | null;
  has_logo: boolean;
  logo_version: number;
}

export interface Branding {
  name: string;
  has_logo: boolean;
  logo_version: number;
  company_id: string | null;
}

export interface Account {
  id: string;
  name: string;
  kind: AccountKind;
  institution: string | null;
  last4: string | null;
  currency: string;
  opening_balance: number;
  opening_date: string | null;
  is_active: boolean;
  balance: number;
  unreviewed_count: number;
  transaction_count: number;
  has_csv_profile: boolean;
}

export interface AccountInput {
  name: string;
  kind: AccountKind;
  institution: string | null;
  last4: string | null;
  opening_balance: number;
  opening_date: string | null;
  is_active: boolean;
}

/** A payment-term code from the company's rules. */
export type Terms = string;

export interface Customer {
  custom?: CustomValues | null;
  id: string;
  name: string;
  email: string | null;
  notes: string | null;
  is_active: boolean;
  cc_emails?: string | null;
  phone?: string | null;
  billing_address?: string | null;
  default_terms?: Terms | null;
  open_balance?: number;
  overdue_balance?: number;
}

export type CustomerInput = Omit<Customer, "id" | "open_balance" | "overdue_balance">;

export interface CsvMapping {
  date_column: number | null;
  description_column: number | null;
  amount_column: number | null;
  debit_column: number | null;
  credit_column: number | null;
  invert_amounts: boolean;
  date_format: string | null;
}

export interface PreviewRow {
  line: number;
  txn_date: string | null;
  amount: number | null;
  description: string;
  error: string | null;
}

export interface ImportPreview {
  source: "csv" | "ofx";
  filename: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  date_from: string | null;
  date_to: string | null;
  money_in: number;
  money_out: number;
  rows: PreviewRow[];
  headers: string[];
  sample: string[][];
  mapping: CsvMapping | null;
  problems: string[];
  file_account_last4: string | null;
  previously_imported: boolean;
}

export interface ImportBatch {
  id: string;
  account_id: string;
  account_name: string;
  source: string;
  filename: string;
  rows_total: number;
  rows_imported: number;
  rows_duplicate: number;
  rows_invalid: number;
  rows_flagged: number;
  status: "active" | "undone";
  created_at: string;
  approved_count: number;
}

export interface PeerTxn {
  id: string;
  account_id: string;
  account_name: string;
  txn_date: string;
  amount: number;
  description: string;
  review_status: ReviewStatus;
}

export interface Txn {
  id: string;
  bill_id: string | null;
  customer_payment_id?: string | null;
  invoice_ids?: string[];
  account_id: string;
  account_name: string;
  account_kind: AccountKind;
  txn_date: string;
  amount: number;
  description: string;
  normalized: string;
  memo: string | null;
  source: "csv" | "ofx" | "manual";
  review_status: ReviewStatus;
  category_id: string | null;
  category_name: string | null;
  allocation_account_id: string | null;
  allocation_account_name: string | null;
  vendor_id: string | null;
  vendor_name: string | null;
  customer_id: string | null;
  customer_name: string | null;
  suggested_category_id: string | null;
  suggested_category_name: string | null;
  suggested_vendor_name: string | null;
  confidence: number;
  suggestion_reason: string | null;
  is_transfer: boolean;
  transfer_peer: PeerTxn | null;
  duplicate_of: PeerTxn | null;
  expense_id: string | null;
  receipt_status: "attached" | "missing" | "not_needed";
  approved_at: string | null;
  reconciled: boolean;
  reconciliation_id: string | null;
}

export interface TxnPage {
  items: Txn[];
  total: number;
  page: number;
  page_size: number;
  counts: { review: number; approved: number; excluded: number };
  total_in: number;
  total_out: number;
}

export interface ReconciliationSummary {
  id: string;
  account_id: string;
  account_name: string;
  account_kind: AccountKind;
  statement_date: string;
  beginning_balance: number;
  ending_balance: number;
  cleared_balance: number;
  difference: number;
  status: "draft" | "completed";
  transaction_count: number;
  statement_filename: string | null;
  statement_size_bytes: number | null;
  notes: string | null;
  created_at: string;
  completed_at: string | null;
  completed_by_name: string | null;
}

export interface Reconciliation extends ReconciliationSummary {
  transactions: Txn[];
}

export interface AuditLogItem {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  user_id: string | null;
  user_name: string | null;
  user_email: string | null;
  changes: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogPage {
  items: AuditLogItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface TxnFilters {
  account_id?: string;
  tab: Tab;
  flag?: TxnFlag | "";
  search?: string;
  date_from?: string;
  date_to?: string;
  sort?: "date_desc" | "date_asc" | "amount_desc" | "amount_asc";
}

export interface TxnUpdate {
  category_id?: string | null;
  vendor_name?: string | null;
  customer_id?: string | null;
  memo?: string | null;
  expense_id?: string | null;
}

export interface ManualTxnInput {
  account_id: string;
  txn_date: string;
  amount: number;
  description: string;
  category_id: string | null;
  vendor_name: string | null;
  customer_id: string | null;
  memo: string | null;
}

export interface BulkResult {
  approved: number;
  skipped: number;
  messages: string[];
}

export interface Candidates {
  transfers: PeerTxn[];
  expenses: ExpenseListItem[];
}

// ---------- v0.4.0: bill import ----------
export interface BillCapabilities {
  ocr: boolean;
  ai_mode: "off" | "fallback" | "always";
  ai_requested: string;
  ai_key_set: boolean;
  ai_model: string;
  formats: string[];
}

export interface BillExtract {
  filename: string;
  method: "text" | "ocr" | "ai";
  vendor_name: string | null;
  expense_date: string | null;
  due_date: string | null;
  amount: number | null;
  invoice_number: string | null;
  description: string | null;
  currency: string;
  category_id: string | null;
  category_reason: string;
  confidence: Record<string, number>;
  sources: Record<string, string>;
  confident: boolean;
  known_vendor: boolean;
  warnings: string[];
  attachments: string[];
  text_preview: string;
  duplicates: ExpenseListItem[];
  bank_match: { id: string; account_name: string; txn_date: string; description: string } | null;
}

// ---------- v0.5.0: multi-company ----------
export interface CompanyListItem {
  id: string;
  name: string;
  role: CompanyRole;
  via_reseller: boolean;
  reseller_id: string | null;
  reseller_name: string | null;
  has_logo: boolean;
  logo_version: number;
  is_current: boolean;
}

export interface Member {
  user_id: string;
  name: string;
  email: string;
  role: CompanyRole;
  via_reseller: boolean;
  is_you: boolean;
  is_active: boolean;
  custom_role_id?: string | null;
  custom_role_name?: string | null;
}

export interface ResellerAdmin {
  user_id: string;
  name: string;
  email: string;
}

export interface Reseller {
  id: string;
  name: string;
  is_active: boolean;
  company_count: number;
  admins: ResellerAdmin[];
}

// ---------- v0.6.0: bills and the books ----------
export type BillTerms = string;
export type BillStatus = "open" | "partial" | "paid" | "overdue";

export interface BillInput {
  custom?: CustomValues | null;
  vendor_name: string;
  bill_date: string;
  terms: BillTerms | null;
  due_date: string | null;
  bill_number: string | null;
  memo: string | null;
  lines: LineInput[];
}

export interface BillListItem {
  id: string;
  vendor_id: string;
  vendor_name: string;
  bill_date: string;
  due_date: string;
  terms: BillTerms | null;
  bill_number: string | null;
  total: number;
  paid: number;
  balance: number;
  status: BillStatus;
  attachment_count: number;
}

export interface BillPayment {
  id: string;
  payment_date: string;
  account_id: string;
  account_name: string;
  amount: number;
  memo: string | null;
  transaction_id: string | null;
}

export interface BillAttachment {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface BillDetail extends BillListItem {
  custom?: CustomValues | null;
  memo: string | null;
  lines: LineOut[];
  payments: BillPayment[];
  attachments: BillAttachment[];
}

export interface BillPage {
  items: BillListItem[];
  total_open: number;
  total_overdue: number;
}

export type AccountType = "asset" | "liability" | "equity" | "income" | "expense";

export interface LedgerAccount {
  id: string;
  code: string | null;
  name: string;
  type: AccountType;
  detail_type: string;
  system_key: string | null;
  description: string | null;
  is_active: boolean;
  balance: number;
  linked_to: "category" | "bank" | "system" | "none";
  category_id: string | null;
  bank_account_id: string | null;
}

export interface LedgerAccountInput {
  code: string | null;
  name: string;
  type: AccountType;
  detail_type: string;
  description: string | null;
  is_active: boolean;
}

export interface RegisterLine {
  entry_id: string;
  entry_date: string;
  source_type: string;
  source_id: string | null;
  number: string | null;
  memo: string | null;
  description: string | null;
  other_accounts: string;
  debit: number;
  credit: number;
  balance: number;
}

export interface Register {
  account: LedgerAccount;
  lines: RegisterLine[];
  opening_balance: number;
}

export interface JournalLineInput {
  account_id: string;
  debit: number;
  credit: number;
  description: string | null;
  customer_id: string | null;
  vendor_name: string | null;
}

export interface JournalEntry {
  id: string;
  entry_date: string;
  source_type: string;
  source_id: string | null;
  number: string | null;
  memo: string | null;
  total: number;
  editable: boolean;
  lines: (JournalLineInput & { account_name: string })[];
}

export interface ReportSection {
  key: string;
  label: string;
  rows: { account_id: string; name: string; code: string | null; amount: number }[];
  total: number;
}

export interface ProfitLoss {
  date_from: string;
  date_to: string;
  sections: ReportSection[];
  gross_profit: number;
  net_operating_income: number;
  net_income: number;
}

export interface BalanceSheet {
  as_of: string;
  sections: ReportSection[];
  total_assets: number;
  total_liabilities_and_equity: number;
  balanced: boolean;
}

export interface TrialBalance {
  as_of: string;
  rows: { account_id: string; name: string; code: string | null; type: AccountType; debit: number; credit: number }[];
  total_debit: number;
  total_credit: number;
}

export interface BooksStatus {
  closing_date: string | null;
  total_debit: number;
  total_credit: number;
  balanced: boolean;
  unbalanced_entries: number;
  payment_account_not_set: number;
}

// ---------- v0.7.0 sales ----------
export type InvoiceStatus = "not_sent" | "sent" | "partial" | "paid" | "overdue" | "void";
export type PaymentMethodIn = string;

export interface Item {
  custom?: CustomValues | null;
  id: string;
  name: string;
  description: string | null;
  rate: number | null;
  category_id: string;
  category_name: string;
  is_active: boolean;
}

export interface ItemInput {
  custom?: CustomValues | null;
  name: string;
  description: string | null;
  rate: number | null;
  category_id: string;
  is_active: boolean;
}

export interface InvoiceLineInput {
  service_date: string | null;
  item_id: string | null;
  description: string | null;
  quantity: number;
  rate: number;
  category_id: string | null;
  expense_line_id: string | null;
  bill_line_id: string | null;
}

export interface InvoiceLineOut extends InvoiceLineInput {
  id: string;
  item_name: string | null;
  amount: number;
  category_name: string | null;
}

export interface InvoiceInput {
  custom?: CustomValues | null;
  customer_id: string;
  invoice_number: string | null;
  invoice_date: string;
  terms: Terms | null;
  due_date: string | null;
  bill_email: string | null;
  message: string | null;
  memo: string | null;
  lines: InvoiceLineInput[];
}

export interface InvoiceListItem {
  id: string;
  invoice_number: string;
  customer_id: string;
  customer_name: string;
  invoice_date: string;
  due_date: string;
  total: number;
  paid: number;
  balance: number;
  status: InvoiceStatus;
  sent_at: string | null;
}

export interface InvoicePaymentRef {
  payment_id: string;
  payment_date: string;
  amount: number;
  payment_total: number;
  account_name: string;
  method: string | null;
  reference: string | null;
  transaction_id: string | null;
}

export interface InvoiceEmail {
  id: string;
  sent_to: string;
  subject: string;
  status: "sent" | "failed";
  error: string | null;
  sent_at: string;
}

export interface InvoiceDetail extends InvoiceListItem {
  custom?: CustomValues | null;
  terms: Terms | null;
  bill_email: string | null;
  customer_email: string | null;
  customer_cc: string | null;
  message: string | null;
  memo: string | null;
  lines: InvoiceLineOut[];
  payments: InvoicePaymentRef[];
  emails: InvoiceEmail[];
  voided_at: string | null;
}

export interface InvoicePage {
  items: InvoiceListItem[];
  total_open: number;
  total_overdue: number;
  paid_last_30: number;
  count_open: number;
  count_overdue: number;
}

export interface Billable {
  source: "expense" | "bill";
  line_id: string;
  record_id: string;
  date: string;
  vendor_name: string | null;
  description: string | null;
  category_name: string;
  amount: number;
}

export interface PaymentInput {
  customer_id: string;
  payment_date: string;
  account_id: string;
  amount: number;
  method: PaymentMethodIn | null;
  reference: string | null;
  memo: string | null;
  transaction_id: string | null;
  applications: { invoice_id: string; amount: number }[];
}

export interface PaymentOut {
  id: string;
  customer_id: string;
  customer_name: string;
  payment_date: string;
  account_id: string;
  account_name: string;
  amount: number;
  method: string | null;
  reference: string | null;
  memo: string | null;
  transaction_id: string | null;
  applications: { invoice_id: string; invoice_number: string; amount: number }[];
}

export interface CustomerDetail extends Customer {
  open_balance: number;
  overdue_balance: number;
  invoice_count: number;
  paid_invoice_count: number;
  avg_days_to_pay: number | null;
  on_time_percent: number | null;
  unbilled_amount: number;
  unbilled_count: number;
  invoices: InvoiceListItem[];
  payments: PaymentOut[];
}

export interface EmailSettings {
  configured: boolean;
  provider: "smtp" | "microsoft";
  oauth_account: string | null;
  ms_client_id: string | null;
  ms_client_id_in_env: boolean;
  ms_tenant: string | null;
  microsoft_ready: boolean;
  smtp_host: string | null;
  smtp_port: number | null;
  security: "starttls" | "ssl" | "none" | null;
  username: string | null;
  has_password: boolean;
  from_email: string | null;
  from_name: string | null;
  reply_to: string | null;
  copy_me: boolean;
}

export interface EmailSettingsInput {
  smtp_host: string;
  smtp_port: number;
  security: "starttls" | "ssl" | "none";
  username: string | null;
  password: string | null;
  from_email: string;
  from_name: string | null;
  reply_to: string | null;
  copy_me: boolean;
}

export interface EmailDraft {
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  configured: boolean;
  from_label: string | null;
}

export interface AgingRow {
  customer_id: string;
  customer_name: string;
  current: number;
  d1_30: number;
  d31_60: number;
  d61_90: number;
  d91_plus: number;
  total: number;
}

export interface Aging {
  as_of: string;
  rows: AgingRow[];
  totals: AgingRow;
}

export interface SalesByCustomer {
  date_from: string;
  date_to: string;
  rows: { customer_id: string | null; customer_name: string; amount: number }[];
  total: number;
}

export interface SalesSummary {
  open_total: number;
  open_count: number;
  overdue_total: number;
  overdue_count: number;
  not_sent_count: number;
  paid_last_30: number;
  deposits_to_match: number;
}

export interface MicrosoftStart {
  flow_id: string;
  user_code: string;
  verification_uri: string;
  interval: number;
  expires_in: number;
}

// ---------- v0.9.0 dashboard ----------
export interface DashPoint { date: string; balance: number }
export interface DashAccount { id: string; name: string; kind: string; institution: string | null; last4: string | null; balance: number; unreviewed: number }
export interface DashMonth { key: string; label: string; income: number; expenses: number }
export interface DashEvent { kind: "invoice" | "bill"; id: string; date: string; name: string; reference: string | null; amount: number; days_late: number }
export interface DashInvoice { id: string; invoice_number: string; customer_name: string; due_date: string; total: number; balance: number; status: string; days_late: number }
export interface DashPnlRow { name: string; this_month: number; last_month: number }
export interface Dashboard {
  as_of: string;
  cash_total: number;
  cash_month_start: number;
  has_bank_accounts: boolean;
  accounts: DashAccount[];
  income_ytd: number;
  expenses_ytd: number;
  profit_ytd: number;
  profit_prior_ytd: number;
  fiscal_year_start: string;
  receivable_total: number;
  receivable_open_count: number;
  overdue_total: number;
  overdue_count: number;
  paid_last_30: number;
  payable_total: number;
  payable_count: number;
  payable_due_14: number;
  payable_overdue: number;
  owner_loan_balance: number;
  owner_reimbursements: number;
  owner_total_owed: number;
  review_count: number;
  months: DashMonth[];
  history: DashPoint[];
  forecast: DashPoint[];
  forecast_low: DashPoint;
  coming_up: DashEvent[];
  invoices: DashInvoice[];
  pnl: {
    this_from: string; this_to: string; last_from: string; last_to: string;
    income_this: number; income_last: number; expense_rows: DashPnlRow[];
    expenses_this: number; expenses_last: number; net_this: number; net_last: number;
  };
}

// ---------- v0.10.0 company rules ----------
export type CustomValues = Record<string, string | number | boolean>;
export type CustomEntity = "customer" | "item" | "invoice" | "bill" | "expense";

export interface Term {
  code: string;
  name: string;
  kind: "days" | "end_of_month" | "day_of_next_month";
  days: number;
  day: number | null;
  active: boolean;
}

export interface Choice { code: string; label: string; active: boolean }

export interface CustomField {
  code: string;
  label: string;
  entity: CustomEntity;
  type: "text" | "number" | "date" | "choice" | "yes_no";
  options: string[];
  required: boolean;
  print_on_invoice: boolean;
  active: boolean;
}

export interface CompanyRules {
  approvals_required: boolean;
  approval_threshold: number | string;
  date_format: "MM/DD/YYYY" | "DD/MM/YYYY" | "YYYY-MM-DD" | "DD.MM.YYYY";
  number_format: "1,234.56" | "1.234,56" | "1 234,56" | "1'234.56";
  currency_symbol: string | null;
  terms: Term[];
  default_terms: string | null;
  bill_default_terms: string | null;
  expense_methods: Choice[];
  received_methods: Choice[];
  custom_fields: CustomField[];
  invoice_prefix: string;
  next_invoice_number: number | null;
  pdf_accent: string;
  pdf_labels: Record<string, string>;
  email_subject: string;
  email_body: string;
  auto_approve_confidence: number;
  forecast_days: 14 | 30 | 60 | 90;
  coming_up_days: 7 | 14 | 30 | 60;
}

export interface RulesResponse {
  currency: string;
  rules: CompanyRules;
  defaults: CompanyRules;
  labels_default: Record<string, string>;
  email_placeholders: string[];
  currency_symbols: Record<string, string>;
}

export interface BankRuleInput {
  name: string;
  priority: number;
  is_active: boolean;
  match_type: "contains" | "starts_with" | "equals" | "not_contains";
  match_text: string;
  direction: "any" | "in" | "out";
  amount_min: number | null;
  amount_max: number | null;
  account_id: string | null;
  category_id: string | null;
  vendor_name: string | null;
  customer_id: string | null;
  memo: string | null;
  auto_approve: boolean;
}

export interface BankRule extends BankRuleInput {
  id: string;
  times_used: number;
  category_name: string | null;
  account_name: string | null;
  customer_name: string | null;
  would_match: number;
}

export interface RoleInput {
  name: string;
  description: string | null;
  base_role: CompanyRole;
  permissions: Record<string, AreaLevel>;
}

export interface CustomRole extends RoleInput {
  id: string;
  effective: Record<string, AreaLevel>;
  member_count: number;
}

export interface RoleAreas {
  areas: Record<string, string>;
  base: Record<string, Record<string, AreaLevel>>;
}

// ---------- v0.10.1 updates ----------
export interface UpdateManifest {
  version: string;
  min_version: string;
  exe_sha256: string;
  exe_size: number;
  notes: string;
  built_at: string;
  kind: "upgrade" | "reinstall";
}

export interface UpdateStatus {
  current_version: string;
  supported: boolean;
  reason: string;
  exe_name: string;
  folder: string;
  staged: UpdateManifest | null;
  last_result: { status?: "ok" | "rolled_back" | "not_installed"; version?: string; when?: string } | null;
  backups: { name: string; bytes: number }[];
}

// ---------- v0.11.0 owner funds and full backups ----------
export type OwnerFundsAction = "loan" | "repayment" | "opening_balance";

export interface OwnerFunds {
  due_to_owner_account_id: string;
  reimbursements_account_id: string;
  loan_balance: number;
  reimbursement_balance: number;
  total_owed: number;
  activity: {
    entry_id: string;
    entry_date: string;
    account: "loan" | "reimbursement";
    source_type: string;
    source_id: string | null;
    description: string;
    change: number;
  }[];
}

export interface BackupInfo {
  name: string;
  bytes: number;
  created_at: string;
  version: string;
  reason: string;
  receipt_count: number;
}

export interface BackupStatus {
  supported: boolean;
  reason: string;
  folder: string;
  backups: BackupInfo[];
  last_result: { status?: "ok" | "rolled_back" | "not_restored" } | null;
}
