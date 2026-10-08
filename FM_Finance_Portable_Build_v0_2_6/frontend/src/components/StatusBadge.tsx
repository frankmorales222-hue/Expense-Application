import { STATUS_LABEL } from "../format";
import type { ExpenseStatus } from "../types";

export default function StatusBadge({ status }: { status: ExpenseStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}
