/** Vocabulario comun de los jobs: un solo sitio para etiquetas y color de estado. */

export interface Job {
  id: string;
  repository_id: string;
  task_type: string;
  status: string;
  trigger: string;
  ref: string;
  model: string;
  prompt: string | null;
  pull_request_url: string | null;
  branch_name: string | null;
  diff_summary: string | null;
  error_message: { error: string; suite_log?: string } | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export type Tone = "success" | "destructive" | "warning" | "primary" | "neutral";

// El color codifica significado: quien vigila jobs lee el estado por el color.
const STATUS: Record<string, { label: string; tone: Tone; active: boolean }> = {
  queued: { label: "En cola", tone: "neutral", active: true },
  running: { label: "Trabajando", tone: "primary", active: true },
  completed: { label: "Completado", tone: "success", active: false },
  failed: { label: "Falló", tone: "destructive", active: false },
  needs_review: { label: "Revisar", tone: "warning", active: false },
};

export function jobStatus(status: string) {
  return STATUS[status] ?? { label: status, tone: "neutral" as Tone, active: false };
}

export const TASKS = [
  { value: "security", label: "Seguridad" },
  { value: "quality", label: "Calidad" },
  { value: "deps", label: "Dependencias" },
  { value: "perf", label: "Rendimiento" },
  { value: "docs", label: "Documentación" },
] as const;

export function taskLabel(task: string): string {
  return TASKS.find((t) => t.value === task)?.label ?? task;
}

const TRIGGERS: Record<string, string> = {
  cron: "Programado",
  webhook: "Push",
  manual: "Manual",
  prompt: "Prompt",
};

export function triggerLabel(trigger: string): string {
  return TRIGGERS[trigger] ?? trigger;
}
