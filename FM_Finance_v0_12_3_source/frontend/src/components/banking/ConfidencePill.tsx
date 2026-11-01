import { confidenceLevel } from "../../format";

const LABEL = { high: "High", medium: "Medium", low: "Low", none: "" } as const;

export default function ConfidencePill({ value, reason }: { value: number; reason?: string | null }) {
  const level = confidenceLevel(value);
  if (level === "none") return null;
  return (
    <span className={`conf conf-${level}`} title={reason ?? undefined}>
      <span className="conf-meter" aria-hidden="true"><span style={{ width: `${value}%` }} /></span>
      {LABEL[level]} {value}%
    </span>
  );
}
