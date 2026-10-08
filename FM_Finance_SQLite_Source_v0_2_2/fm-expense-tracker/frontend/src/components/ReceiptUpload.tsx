import { useRef, useState, type DragEvent } from "react";
import { api } from "../api";
import { fileSize, formatDateTime } from "../format";
import type { Receipt } from "../types";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.heic";
const ALLOWED_EXT = ["pdf", "jpg", "jpeg", "png", "heic"];

export function validateReceipt(file: File, maxMb: number): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ALLOWED_EXT.includes(ext)) return `${file.name}: only PDF, JPG, PNG or HEIC files can be attached.`;
  if (file.size > maxMb * 1024 * 1024) return `${file.name} is larger than ${maxMb} MB.`;
  return null;
}

/**
 * Two modes:
 *  - Saved expense: files upload immediately (onUpload) and existing receipts are listed.
 *  - New expense: files are queued (pending) and uploaded after the expense is saved.
 */
export default function ReceiptUpload({ receipts, pending, maxMb, busy, onAdd, onRemovePending, onDelete }: {
  receipts: Receipt[];
  pending: File[];
  maxMb: number;
  busy: boolean;
  onAdd: (files: File[]) => void;
  onRemovePending: (index: number) => void;
  onDelete?: (r: Receipt) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) onAdd(Array.from(e.dataTransfer.files));
  }

  return (
    <div className="receipts">
      <div
        className={dragging ? "dropzone dragging" : "dropzone"}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <p>Drop receipts here or</p>
        <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}>
          {busy ? "Uploading…" : "Choose files"}
        </button>
        <p className="hint">PDF, JPG, PNG or HEIC, up to {maxMb} MB each</p>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) onAdd(Array.from(e.target.files));
            e.target.value = "";
          }}
        />
      </div>

      {(receipts.length > 0 || pending.length > 0) && (
        <ul className="receipt-list">
          {receipts.map((r) => (
            <li key={r.id}>
              <div>
                <a href={api.receiptUrl(r.id)} target="_blank" rel="noopener">{r.original_filename}</a>
                <span className="muted"> {fileSize(r.size_bytes)}, added {formatDateTime(r.uploaded_at)}</span>
              </div>
              {onDelete && (
                <button type="button" className="link-button danger" onClick={() => onDelete(r)}>Remove</button>
              )}
            </li>
          ))}
          {pending.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <div>
                {f.name} <span className="muted"> {fileSize(f.size)}, uploads when you save</span>
              </div>
              <button type="button" className="link-button" onClick={() => onRemovePending(i)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
