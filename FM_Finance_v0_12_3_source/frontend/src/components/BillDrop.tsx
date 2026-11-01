import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDate, money } from "../format";
import type { BillCapabilities, BillExtract } from "../types";

const ACCEPT = ".pdf,.docx,.eml,.msg,.jpg,.jpeg,.png,.webp,.heic";
const METHOD_LABEL: Record<BillExtract["method"], string> = {
  text: "Read from the file's text",
  ocr: "Read with offline OCR",
  ai: "Read with AI",
};

interface Props {
  onFilled: (result: BillExtract, file: File) => void;
}

export default function BillDrop({ onFilled }: Props) {
  const [caps, setCaps] = useState<BillCapabilities | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<BillExtract | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api.billCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);

  async function read(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.extractBill(file);
      setResult(r);
      onFilled(r, file);
    } catch (e) {
      setError(e instanceof Error ? e.message : "This file couldn't be read");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    void read(e.dataTransfer.files?.[0]);
  }

  return (
    <section className="bill-drop-wrap">
      <div className={`bill-drop${dragging ? " dragging" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
        <div>
          <strong>{busy ? "Reading the bill…" : "Fill this in from a bill"}</strong>
          <p className="hint">
            {busy ? "Scans and photos can take a few seconds." :
              "Drop a PDF, Word file, email (.eml or .msg) or photo. The fields fill in for you to check, and the file is attached as the receipt."}
          </p>
        </div>
        <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}>Choose file</button>
        <input ref={input} type="file" hidden accept={ACCEPT} onChange={(e) => void read(e.target.files?.[0])} />
      </div>
      {caps && (
        <p className="hint bill-caps">
          Offline reading {caps.ocr ? "with OCR for scans and photos" : "(OCR unavailable)"}.{" "}
          {caps.ai_mode === "off"
            ? (caps.ai_requested !== "off" && !caps.ai_key_set ? "AI reading is on but no API key is set." : "AI reading is off.")
            : caps.ai_mode === "fallback" ? "AI reading helps when offline reading isn't sure." : "AI reads every bill."}
        </p>
      )}

      {error && <div className="callout callout-error"><p>{error}</p></div>}

      {result && (
        <div className="bill-result">
          <div className="bill-result-head">
            <span className={`method method-${result.method}`}>{METHOD_LABEL[result.method]}</span>
            <span className={result.confident ? "conf-text ok" : "conf-text check"}>
              {result.confident ? "Looks complete. Check before saving." : "Some fields need checking (marked below)."}
            </span>
          </div>
          {result.attachments.length > 0 && <p className="hint">Also read the attachment: {result.attachments.join(", ")}</p>}
          {result.warnings.map((w) => <p key={w} className="hint warn-text">{w}</p>)}
          {result.duplicates.length > 0 && (
            <div className="callout callout-warn">
              <strong>This bill may already be entered</strong>
              {result.duplicates.map((d) => (
                <p key={d.id}><Link to={`/expenses/${d.id}`}>{formatDate(d.expense_date)} {d.vendor_name ?? d.description}, {money(d.amount)}</Link></p>
              ))}
            </div>
          )}
          {result.bank_match && (
            <p className="hint ok-text">
              Matches the bank charge on {formatDate(result.bank_match.txn_date)} in {result.bank_match.account_name}. Saving links them.
            </p>
          )}
          {result.text_preview && (
            <button type="button" className="link-button" onClick={() => setShowText((s) => !s)}>
              {showText ? "Hide" : "Show"} the text that was read
            </button>
          )}
          {showText && <pre className="bill-text">{result.text_preview}</pre>}
        </div>
      )}
    </section>
  );
}
