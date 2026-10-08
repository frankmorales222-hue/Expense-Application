import { money } from "../format";
import type { Summary } from "../types";

export default function SummaryCards({ summary, approvalRequired, currency }: {
  summary: Summary; approvalRequired: boolean; currency: string;
}) {
  return (
    <section className="figures" aria-label="Summary">
      <div className="figure figure-lead">
        <span className="figure-label">Total spent</span>
        <span className="figure-value">{money(summary.total_spent, currency)}</span>
        <span className="figure-note">{summary.expense_count} {summary.expense_count === 1 ? "expense" : "expenses"}</span>
      </div>
      {approvalRequired && (
        <div className="figure">
          <span className="figure-label">Waiting for approval</span>
          <span className="figure-value">{money(summary.pending_amount, currency)}</span>
          <span className="figure-note">{summary.pending_count} pending</span>
        </div>
      )}
      <div className="figure">
        <span className="figure-label">Owed back to you</span>
        <span className="figure-value">{money(summary.reimbursable_owed, currency)}</span>
        <span className="figure-note">Paid personally, not yet reimbursed</span>
      </div>
    </section>
  );
}
