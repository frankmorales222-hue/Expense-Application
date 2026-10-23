import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../context";
import { ACCOUNT_KIND_LABEL, formatDate, formatDateTime, money } from "../format";
import type { Account, CsvMapping, ImportBatch, ImportPreview } from "../types";

const DATE_FORMATS = [
  { value: "%m/%d/%Y", label: "10/04/2026" },
  { value: "%m/%d/%y", label: "10/04/26" },
  { value: "%Y-%m-%d", label: "2026-10-04" },
  { value: "%m-%d-%Y", label: "10-04-2026" },
  { value: "%d/%m/%Y", label: "04/10/2026 (day first)" },
  { value: "%Y/%m/%d", label: "2026/10/04" },
  { value: "%b %d, %Y", label: "Oct 04, 2026" },
  { value: "%d-%b-%Y", label: "04-Oct-2026" },
];

export default function ImportPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState(params.get("account") ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<CsvMapping | null>(null);
  const [result, setResult] = useState<ImportBatch | null>(null);
  const [history, setHistory] = useState<ImportBatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const loadHistory = useCallback(() => {
    api.imports().then(setHistory).catch(() => setHistory([]));
  }, []);

  useEffect(() => {
    api.accounts().then((a) => {
      setAccounts(a);
      setAccountId((cur) => cur || a[0]?.id || "");
    }).catch((e: Error) => toast.error(e.message));
    loadHistory();
  }, [toast, loadHistory]);

  const runPreview = useCallback(async (f: File, acct: string, m: CsvMapping | null) => {
    if (!acct) return;
    setBusy(true);
    try {
      const p = await api.previewImport(acct, f, m);
      setPreview(p);
      setMapping(p.mapping);
    } catch (e) {
      setPreview(null);
      toast.error(e instanceof Error ? e.message : "Could not read the file");
    } finally {
      setBusy(false);
    }
  }, [toast]);

  function choose(f: File | null | undefined) {
    if (!f) return;
    setFile(f);
    setResult(null);
    void runPreview(f, accountId, null);
  }

  function changeAccount(id: string) {
    setAccountId(id);
    if (file) void runPreview(file, id, null);
  }

  function updateMapping(patch: Partial<CsvMapping>) {
    if (!mapping || !file) return;
    const next = { ...mapping, ...patch };
    setMapping(next);
    void runPreview(file, accountId, next);
  }

  async function commit() {
    if (!file || !accountId) return;
    setBusy(true);
    try {
      const r = await api.commitImport(accountId, file, preview?.source === "csv" ? mapping : null);
      setResult(r);
      setPreview(null);
      setFile(null);
      if (input.current) input.current.value = "";
      loadHistory();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  async function undo(b: ImportBatch) {
    if (!window.confirm(`Remove the ${b.rows_imported} transactions imported from ${b.filename}?`)) return;
    try {
      await api.undoImport(b.id);
      toast.success("Import undone");
      if (result?.id === b.id) setResult(null);
      loadHistory();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not undo");
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files?.[0]);
  }

  const account = accounts.find((a) => a.id === accountId);
  const singleAmount = mapping ? mapping.amount_column !== null || (mapping.debit_column === null && mapping.credit_column === null) : true;
  const last4Mismatch = preview?.file_account_last4 && account?.last4 && preview.file_account_last4 !== account.last4;
  const canImport = !!preview && preview.problems.length === 0 && preview.valid_rows > 0 && !busy;

  if (accounts.length === 0) {
    return (
      <div className="page">
        <header className="page-head"><div><Link to="/banking" className="back">Banking</Link><h1>Import statement</h1></div></header>
        <div className="empty"><p>Add an account first, then import its statements.</p>
          <Link className="btn btn-primary" to="/accounts">Add an account</Link></div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-head">
        <div><Link to="/banking" className="back">Banking</Link><h1>Import statement</h1></div>
      </header>

      {result && (
        <section className="panel result-panel">
          <h2>Imported {result.rows_imported} transaction{result.rows_imported === 1 ? "" : "s"} into {result.account_name}</h2>
          <ul className="result-list">
            {result.rows_duplicate > 0 && <li>{result.rows_duplicate} already in F&amp;M Finance, skipped</li>}
            {result.rows_flagged > 0 && <li>{result.rows_flagged} flagged as possible duplicates for you to check</li>}
            {result.rows_invalid > 0 && <li>{result.rows_invalid} rows couldn't be read and were left out</li>}
          </ul>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={() => navigate(`/banking?account=${result.account_id}`)}>Review transactions</button>
            <button type="button" className="btn" onClick={() => setResult(null)}>Import another file</button>
          </div>
        </section>
      )}

      {!result && (
        <section className="panel">
          <div className="import-top">
            <label className="field"><span>Account</span>
              <select value={accountId} onChange={(e) => changeAccount(e.target.value)}>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({ACCOUNT_KIND_LABEL[a.kind]}{a.last4 ? ` ${a.last4}` : ""})</option>)}
              </select></label>
            <div className={dragging ? "dropzone dragging" : "dropzone"} onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <p>{file ? <strong>{file.name}</strong> : "Drop a CSV, OFX or QFX file here"}</p>
              <button type="button" className="btn" onClick={() => input.current?.click()}>{file ? "Choose a different file" : "Choose file"}</button>
              <input ref={input} type="file" hidden accept=".csv,.txt,.ofx,.qfx,.qbo" onChange={(e) => choose(e.target.files?.[0])} />
              <span className="hint">OFX/QFX is the most reliable: each transaction has a bank ID, so re-importing never creates duplicates.</span>
            </div>
          </div>
        </section>
      )}

      {preview && !result && (
        <>
          {(preview.previously_imported || last4Mismatch || preview.invalid_rows > 0) && (
            <div className="callout callout-warn">
              {preview.previously_imported && <p>This exact file was imported into {account?.name} before. Transactions already there will be skipped.</p>}
              {last4Mismatch && <p>The file is for an account ending {preview.file_account_last4}, but {account?.name} ends {account?.last4}. Check you picked the right account.</p>}
              {preview.invalid_rows > 0 && <p>{preview.invalid_rows} row{preview.invalid_rows === 1 ? "" : "s"} can't be read and will be left out.</p>}
            </div>
          )}

          <div className="figures">
            <div className="figure"><span className="figure-label">Transactions</span><span className="figure-value">{preview.valid_rows}</span>
              {preview.date_from && <span className="figure-note">{formatDate(preview.date_from)} to {formatDate(preview.date_to ?? preview.date_from)}</span>}</div>
            <div className="figure"><span className="figure-label">Money in</span><span className="figure-value amount-in">{money(preview.money_in)}</span></div>
            <div className="figure"><span className="figure-label">Money out</span><span className="figure-value">{money(preview.money_out)}</span></div>
          </div>

          {preview.source === "csv" && mapping && (
            <section className="panel">
              <h2>Columns</h2>
              <p className="muted">Check that money out shows as negative below. Your choices are remembered for {account?.name}.</p>
              {preview.problems.length > 0 && <div className="callout callout-error">{preview.problems.map((p) => <p key={p}>{p}</p>)}</div>}
              <div className="mapping-grid">
                <ColumnSelect label="Date" headers={preview.headers} value={mapping.date_column} onChange={(v) => updateMapping({ date_column: v, date_format: null })} />
                <label className="field"><span>Date format</span>
                  <select value={mapping.date_format ?? ""} onChange={(e) => updateMapping({ date_format: e.target.value || null })}>
                    <option value="">Detect</option>
                    {DATE_FORMATS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select></label>
                <ColumnSelect label="Description" headers={preview.headers} value={mapping.description_column} onChange={(v) => updateMapping({ description_column: v })} />
                <label className="field"><span>Amounts are in</span>
                  <select value={singleAmount ? "single" : "split"} onChange={(e) => updateMapping(e.target.value === "single"
                    ? { amount_column: mapping.debit_column ?? mapping.credit_column ?? 0, debit_column: null, credit_column: null }
                    : { amount_column: null, debit_column: 0, credit_column: 0 })}>
                    <option value="single">One amount column</option>
                    <option value="split">Separate debit and credit columns</option>
                  </select></label>
                {singleAmount ? (
                  <ColumnSelect label="Amount" headers={preview.headers} value={mapping.amount_column} onChange={(v) => updateMapping({ amount_column: v })} />
                ) : (
                  <>
                    <ColumnSelect label="Debit (money out)" headers={preview.headers} value={mapping.debit_column} onChange={(v) => updateMapping({ debit_column: v })} />
                    <ColumnSelect label="Credit (money in)" headers={preview.headers} value={mapping.credit_column} onChange={(v) => updateMapping({ credit_column: v })} />
                  </>
                )}
              </div>
              {singleAmount && (
                <label className="check invert">
                  <input type="checkbox" checked={mapping.invert_amounts} onChange={(e) => updateMapping({ invert_amounts: e.target.checked })} />
                  <span>Purchases appear as positive numbers in this file (common for credit cards)</span>
                </label>
              )}
            </section>
          )}

          <section className="panel flush">
            <div className="table-wrap">
              <table className="ledger preview-table">
                <thead><tr><th>Line</th><th>Date</th><th>Description</th><th className="num">Amount</th></tr></thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.line} className={r.error ? "row-error" : ""}>
                      <td className="muted">{r.line}</td>
                      <td className="nowrap">{r.txn_date ? formatDate(r.txn_date) : ""}</td>
                      <td>{r.description}{r.error && <span className="row-error-text"> {r.error}</span>}</td>
                      <td className={r.amount !== null && r.amount > 0 ? "num amount-in" : "num"}>
                        {r.amount !== null ? `${r.amount > 0 ? "+" : ""}${money(r.amount)}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.total_rows > preview.rows.length && <p className="hint table-note">Showing the first {preview.rows.length} of {preview.total_rows} rows.</p>}
          </section>

          <div className="form-actions">
            <span className="spacer" />
            <button type="button" className="btn" onClick={() => { setPreview(null); setFile(null); }}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={!canImport} onClick={() => void commit()}>
              {busy ? "Working…" : `Import ${preview.valid_rows} transaction${preview.valid_rows === 1 ? "" : "s"}`}
            </button>
          </div>
        </>
      )}

      <section className="panel flush">
        <div className="panel-head padded"><h2>Recent imports</h2></div>
        {history.length === 0 ? <p className="muted padded">No imports yet.</p> : (
          <div className="table-wrap">
            <table className="ledger settings-table">
              <thead><tr><th>When</th><th>Account</th><th>File</th><th className="num">Added</th><th className="num">Skipped</th><th /></tr></thead>
              <tbody>
                {history.map((b) => (
                  <tr key={b.id} className={b.status === "undone" ? "inactive" : ""}>
                    <td className="nowrap">{formatDateTime(b.created_at)}</td>
                    <td>{b.account_name}</td>
                    <td className="file-cell">{b.filename}</td>
                    <td className="num">{b.rows_imported}</td>
                    <td className="num">{b.rows_duplicate + b.rows_invalid}</td>
                    <td className="row-actions">
                      {b.status === "undone" ? <span className="muted">Undone</span> : (
                        <button type="button" className="btn btn-small" disabled={b.approved_count > 0}
                          title={b.approved_count > 0 ? "Move its approved transactions back to review first" : "Remove everything this import added"}
                          onClick={() => void undo(b)}>Undo</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function ColumnSelect({ label, headers, value, onChange }: {
  label: string; headers: string[]; value: number | null; onChange: (v: number | null) => void;
}) {
  return (
    <label className="field"><span>{label}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}>
        <option value="">Not in file</option>
        {headers.map((h, i) => <option key={i} value={i}>{h || `Column ${i + 1}`}</option>)}
      </select>
    </label>
  );
}
