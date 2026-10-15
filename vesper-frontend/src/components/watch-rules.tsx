"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  CRON_PRESET_LABELS,
  TASK_TYPES,
  cronFromPreset,
  presetFromCron,
  type CronPreset,
  type TaskType,
  type WatchRule,
} from "@/schemas/watch-rules";

/** Fecha en UTC explicito: el backend no guarda zonas horarias por regla. */
function formatUtc(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const dia = d.toISOString().slice(5, 10).replace("-", "/");
  const hora = d.toISOString().slice(11, 16);
  return `${dia} ${hora} UTC`;
}

interface Props {
  repositoryId: string;
  defaultBranch: string;
}

export function WatchRules({ repositoryId, defaultBranch }: Props) {
  const [rules, setRules] = useState<WatchRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<TaskType | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get(`/repositories/${repositoryId}/watch-rules`)
      .then((r) => setRules(r.data ?? []))
      // Un catch vacio aqui convertiria un fallo de sesion en "no hay reglas".
      .catch(() => setError("No se pudieron cargar las reglas."))
      .finally(() => setLoading(false));
  }, [repositoryId]);

  function upsertLocal(rule: WatchRule) {
    setRules((prev) => {
      const otras = prev.filter((r) => r.id !== rule.id);
      return [...otras, rule];
    });
  }

  async function crear(taskType: TaskType) {
    setBusy(taskType);
    setError("");
    try {
      const r = await api.post(`/repositories/${repositoryId}/watch-rules`, {
        task_type: taskType,
        on_push: true,
      });
      upsertLocal(r.data);
    } catch {
      setError("No se pudo crear la regla.");
    } finally {
      setBusy(null);
    }
  }

  async function actualizar(rule: WatchRule, cambios: Partial<WatchRule>) {
    setBusy(rule.task_type);
    setError("");
    try {
      const r = await api.patch(`/watch-rules/${rule.id}`, cambios);
      upsertLocal(r.data);
    } catch {
      setError("No se pudo guardar el cambio. Revisa la expresión cron.");
    } finally {
      setBusy(null);
    }
  }

  async function borrar(rule: WatchRule) {
    setBusy(rule.task_type);
    setError("");
    try {
      await api.delete(`/watch-rules/${rule.id}`);
      setRules((prev) => prev.filter((r) => r.id !== rule.id));
    } catch {
      setError("No se pudo eliminar la regla.");
    } finally {
      setBusy(null);
    }
  }

  async function cambiarCadencia(rule: WatchRule, preset: CronPreset) {
    if (preset === "custom") {
      const valor = window.prompt(
        "Expresión cron en UTC (minuto hora día mes día-semana):",
        rule.cron ?? "0 3 * * *",
      );
      if (valor === null) return;
      await actualizar(rule, { cron: valor.trim() });
      return;
    }
    await actualizar(rule, { cron: cronFromPreset(preset) });
  }

  if (loading) {
    return <p className="text-xs text-muted-foreground">Cargando reglas...</p>;
  }

  return (
    <div className="space-y-2">
      {error && <p className="text-xs text-red-400">{error}</p>}

      {TASK_TYPES.map(({ value, label }) => {
        const rule = rules.find((r) => r.task_type === value);
        const ocupado = busy === value;

        if (!rule) {
          return (
            <div
              key={value}
              className="flex items-center justify-between rounded-md border border-dashed px-3 py-2"
            >
              <span className="text-sm text-muted-foreground">{label}</span>
              <button
                onClick={() => crear(value)}
                disabled={ocupado}
                className="text-xs underline disabled:opacity-50"
              >
                {/* "Activar" y no "Vigilar": en esta misma pantalla "Vigilar"
                    ya significa enrolar un repo, que es otra cosa. */}
                {ocupado ? "..." : "Activar"}
              </button>
            </div>
          );
        }

        return (
          <div
            key={value}
            className={`rounded-md border px-3 py-2 ${rule.enabled ? "" : "opacity-60"}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">{label}</span>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={rule.on_push}
                    disabled={ocupado}
                    onChange={(e) => actualizar(rule, { on_push: e.target.checked })}
                  />
                  en push a {defaultBranch}
                </label>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={rule.enabled}
                    disabled={ocupado}
                    onChange={(e) => actualizar(rule, { enabled: e.target.checked })}
                  />
                  activa
                </label>
                <button
                  onClick={() => borrar(rule)}
                  disabled={ocupado}
                  className="text-xs text-muted-foreground underline disabled:opacity-50"
                >
                  Quitar
                </button>
              </div>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-3">
              <select
                value={presetFromCron(rule.cron)}
                disabled={ocupado}
                onChange={(e) => cambiarCadencia(rule, e.target.value as CronPreset)}
                className="rounded-md border border-input bg-background px-2 py-1 text-xs"
              >
                {(Object.keys(CRON_PRESET_LABELS) as CronPreset[]).map((p) => (
                  <option key={p} value={p}>
                    {CRON_PRESET_LABELS[p]}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted-foreground">
                {rule.cron ? <code>{rule.cron}</code> : "solo en push"}
                {" · próxima: "}
                {formatUtc(rule.next_run_at)}
                {" · última: "}
                {formatUtc(rule.last_run_at)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
