import { jobStatus, type Tone } from "@/lib/jobs";
import { cn } from "@/lib/utils";

const TONES: Record<Tone, string> = {
  success: "bg-success-soft text-success",
  destructive: "bg-destructive-soft text-destructive",
  warning: "bg-warning-soft text-warning",
  primary: "bg-primary-soft text-primary",
  neutral: "bg-muted text-ink-2",
};

/** Estado de un job: color por significado y texto siempre visible (no solo color). */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const { label, tone } = jobStatus(status);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 rounded-full bg-current", status === "running" && "animate-pulse")}
      />
      {label}
    </span>
  );
}
