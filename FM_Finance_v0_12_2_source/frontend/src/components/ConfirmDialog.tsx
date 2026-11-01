import { useEffect, useRef, type ReactNode } from "react";

export default function ConfirmDialog({ open, title, message, confirmLabel, danger, busy, children, onConfirm, onCancel }: {
  open: boolean; title: string; message: string; confirmLabel: string; danger?: boolean; busy?: boolean;
  children?: ReactNode;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog ref={ref} className="dialog" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h2>{title}</h2>
      <p>{message}</p>
      {children}
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className={danger ? "btn btn-danger" : "btn btn-primary"} onClick={onConfirm} disabled={busy}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
