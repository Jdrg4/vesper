import { z } from "zod";

// Reglas de vigilancia de un repo (F5). Una regla = repo x tarea, con cadencia
// cron y/o disparo en push.
export const watchRuleSchema = z.object({
  id: z.string().uuid(),
  repository_id: z.string().uuid(),
  task_type: z.enum(["security", "quality", "deps", "perf", "docs"]),
  cron: z.string().nullable(),
  on_push: z.boolean(),
  ref: z.string().nullable(),
  enabled: z.boolean(),
  next_run_at: z.string().nullable(),
  last_run_at: z.string().nullable(),
  created_at: z.string(),
});

export type WatchRule = z.infer<typeof watchRuleSchema>;
export type TaskType = WatchRule["task_type"];

export const TASK_TYPES: { value: TaskType; label: string }[] = [
  { value: "security", label: "Seguridad" },
  { value: "quality", label: "Calidad" },
  { value: "deps", label: "Dependencias" },
  { value: "perf", label: "Performance" },
  { value: "docs", label: "Documentación" },
];

// Presets de cadencia. Pedirle una expresion cron a un usuario es una trampa;
// la expresion cruda sigue disponible como "personalizado". Las horas son UTC
// porque el backend no guarda zonas horarias por regla.
export const CRON_PRESETS = {
  hourly: "0 * * * *",
  daily: "0 3 * * *",
  weekly: "0 3 * * 1",
} as const;

export type CronPreset = keyof typeof CRON_PRESETS | "none" | "custom";

export const CRON_PRESET_LABELS: Record<CronPreset, string> = {
  none: "Sin cadencia",
  hourly: "Cada hora",
  daily: "Cada día (03:00 UTC)",
  weekly: "Cada lunes (03:00 UTC)",
  custom: "Personalizado",
};

export function cronFromPreset(preset: CronPreset): string | null {
  if (preset === "none" || preset === "custom") return null;
  return CRON_PRESETS[preset];
}

/** Preset que corresponde a una expresion guardada. `custom` si no casa. */
export function presetFromCron(cron: string | null): CronPreset {
  if (!cron) return "none";
  const match = (Object.keys(CRON_PRESETS) as (keyof typeof CRON_PRESETS)[]).find(
    (k) => CRON_PRESETS[k] === cron,
  );
  return match ?? "custom";
}
