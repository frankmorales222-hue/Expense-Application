import { ACCOUNT_KIND_LABEL, money } from "../../format";
import type { Account } from "../../types";

interface Props {
  accounts: Account[];
  selected: string;
  onSelect: (id: string) => void;
}

export default function AccountStrip({ accounts, selected, onSelect }: Props) {
  const totalReview = accounts.reduce((n, a) => n + a.unreviewed_count, 0);
  return (
    <div className="acct-strip" role="tablist" aria-label="Accounts">
      <button type="button" role="tab" aria-selected={selected === ""}
        className={selected === "" ? "acct-tile active" : "acct-tile"} onClick={() => onSelect("")}>
        <span className="acct-name">All accounts</span>
        <span className="acct-meta">{accounts.length} account{accounts.length === 1 ? "" : "s"}</span>
        {totalReview > 0 && <span className="acct-review">{totalReview} to review</span>}
      </button>
      {accounts.map((a) => {
        const card = a.kind === "credit_card";
        const owed = card && a.balance < 0;
        return (
          <button key={a.id} type="button" role="tab" aria-selected={selected === a.id}
            className={selected === a.id ? "acct-tile active" : "acct-tile"} onClick={() => onSelect(a.id)}>
            <span className="acct-name">{a.name}</span>
            <span className="acct-meta">
              {ACCOUNT_KIND_LABEL[a.kind]}{a.last4 ? ` ending ${a.last4}` : ""}
            </span>
            <span className={a.balance < 0 && !card ? "acct-balance negative" : "acct-balance"}>
              {owed ? `${money(-a.balance)} owed` : money(a.balance)}
            </span>
            {a.unreviewed_count > 0 && <span className="acct-review">{a.unreviewed_count} to review</span>}
          </button>
        );
      })}
    </div>
  );
}
