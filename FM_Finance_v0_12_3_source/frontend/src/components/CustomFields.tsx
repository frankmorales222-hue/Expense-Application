import { useAuth } from "../context";
import type { CustomEntity, CustomField, CustomValues } from "../types";

/** The company's own fields for a kind of record (v0.10.0). Renders nothing when the company has none. */
export default function CustomFields({ entity, value, onChange, disabled = false }: {
  entity: CustomEntity;
  value: CustomValues | null | undefined;
  onChange: (next: CustomValues) => void;
  disabled?: boolean;
}) {
  const { rules } = useAuth();
  const current = value ?? {};
  // Active fields, plus turned-off ones that still hold a value on this record (shown read-only).
  const fields = (rules?.rules.custom_fields ?? []).filter(
    (f) => f.entity === entity && (f.active || current[f.code] !== undefined));
  if (fields.length === 0) return null;

  function set(code: string, v: string | number | boolean | null) {
    const next = { ...current };
    if (v === null || v === "") delete next[code];
    else next[code] = v;
    onChange(next);
  }

  return (
    <fieldset className="custom-fields">
      <legend>More details</legend>
      <div className="custom-grid">
        {fields.map((f) => (
          <FieldInput key={f.code} field={f} value={current[f.code]} disabled={disabled || !f.active}
            onChange={(v) => set(f.code, v)} />
        ))}
      </div>
    </fieldset>
  );
}

function FieldInput({ field: f, value, disabled, onChange }: {
  field: CustomField;
  value: string | number | boolean | undefined;
  disabled: boolean;
  onChange: (v: string | number | boolean | null) => void;
}) {
  const id = `cf-${f.entity}-${f.code}`;
  const label = <span>{f.label}{f.required && <span className="req" aria-hidden="true"> *</span>}</span>;
  if (f.type === "yes_no") {
    return (
      <label className="check" htmlFor={id}>
        <input id={id} type="checkbox" checked={value === true} disabled={disabled}
          onChange={(e) => onChange(e.target.checked)} />
        {f.label}
      </label>
    );
  }
  if (f.type === "choice") {
    return (
      <label className="field" htmlFor={id}>{label}
        <select id={id} value={value === undefined ? "" : String(value)} disabled={disabled} required={f.required}
          onChange={(e) => onChange(e.target.value || null)}>
          <option value="">{f.required ? "Choose…" : "—"}</option>
          {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="field" htmlFor={id}>{label}
      <input id={id} disabled={disabled} required={f.required}
        type={f.type === "date" ? "date" : "text"} inputMode={f.type === "number" ? "decimal" : undefined}
        maxLength={f.type === "text" ? 500 : undefined}
        value={value === undefined ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** Custom values as label: value pairs, for detail views. */
export function customSummary(fields: CustomField[], entity: CustomEntity, value: CustomValues | null | undefined) {
  if (!value) return [];
  return fields.filter((f) => f.entity === entity && value[f.code] !== undefined)
    .map((f) => ({ label: f.label, value: f.type === "yes_no" ? (value[f.code] ? "Yes" : "No") : String(value[f.code]) }));
}
