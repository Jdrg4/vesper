"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const MAX_PROMPT = 4000;

interface Job {
  id: string; repository_id: string; task_type: string; status: string;
  trigger: string;
  ref: string; model: string; pull_request_url: string | null;
  diff_summary: string | null; error_message: { error: string } | null;
  started_at: string | null; completed_at: string | null;
  created_at: string;
}

const TRIGGER_LABELS: Record<string, string> = {
  cron: "programado",
  webhook: "push",
  manual: "manual",
  prompt: "prompt",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [repoId, setRepoId] = useState("");
  const [taskType, setTaskType] = useState("security");
  const [repos, setRepos] = useState<{ id: string; full_name: string }[]>([]);
  const [prompt, setPrompt] = useState("");
  const [showPrompt, setShowPrompt] = useState(false);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    Promise.all([api.get("/jobs"), api.get("/repositories?enrolled=true")])
      .then(([j, r]) => { setJobs(j.data ?? []); setRepos(r.data ?? []); })
      // Antes se tragaba el error: un 401 se veia como "no hay jobs" y un
      // workspace lleno parecia vacio.
      .catch(() => setError("No se pudieron cargar los jobs. ¿Sigue abierta la sesión?"))
      .finally(() => setLoading(false));
  }, []);

  async function handleTrigger() {
    if (!repoId) return;
    setSending(true);
    setError("");
    try {
      await api.post("/jobs", {
        repository_id: repoId,
        task_type: taskType,
        // Sin texto se manda `null` y el backend usa la plantilla del task_type.
        prompt: showPrompt && prompt.trim() ? prompt.trim() : null,
      });
      setPrompt("");
      const r = await api.get("/jobs");
      setJobs(r.data ?? []);
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response?.status;
      setError(
        status === 429
          ? "Has alcanzado el límite de jobs diarios de tu plan."
          : "No se pudo lanzar el job.",
      );
    } finally {
      setSending(false);
    }
  }

  const statusColor = (s: string) => {
    switch (s) {
      case "completed": return "text-green-400";
      case "failed": return "text-red-400";
      case "running": return "text-blue-400";
      case "needs_review": return "text-yellow-400";
      default: return "text-muted-foreground";
    }
  };

  return (
    <main className="min-h-screen p-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold mb-6">Jobs</h1>

      <div className="flex gap-3 mb-8 flex-wrap">
        <select
          value={repoId}
          onChange={(e) => setRepoId(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
        >
          <option value="">Seleccionar repo...</option>
          {repos.map((r) => (
            <option key={r.id} value={r.id}>{r.full_name}</option>
          ))}
        </select>
        <select
          value={taskType}
          onChange={(e) => setTaskType(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
        >
          <option value="security">Seguridad</option>
          <option value="quality">Calidad</option>
          <option value="deps">Deps</option>
          <option value="perf">Performance</option>
          <option value="docs">Docs</option>
        </select>
        <button
          onClick={() => setShowPrompt((v) => !v)}
          className="rounded-md border border-input px-4 py-2 text-sm"
        >
          {showPrompt ? "Usar plantilla" : "Prompt libre"}
        </button>
        <button
          onClick={handleTrigger}
          disabled={!repoId || sending}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {sending ? "Lanzando..." : "Revisar"}
        </button>
      </div>

      {showPrompt && (
        <div className="mb-8">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            maxLength={MAX_PROMPT}
            rows={4}
            placeholder="Migra este módulo a Pydantic v2 y actualiza los tests."
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Sustituye a la plantilla de la tarea. La tarea elegida se conserva como
            etiqueta. {prompt.length}/{MAX_PROMPT}
          </p>
        </div>
      )}

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {loading ? (
        <p className="text-muted-foreground">Cargando...</p>
      ) : jobs.length === 0 ? (
        <p className="text-muted-foreground">No hay jobs. Selecciona un repo vigilado y haz click en Revisar.</p>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <div key={job.id} className="rounded-lg border p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{job.task_type}</span>
                  <span className="rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    {TRIGGER_LABELS[job.trigger] ?? job.trigger}
                  </span>
                </div>
                <span className={`text-sm font-medium ${statusColor(job.status)}`}>
                  {job.status}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                ref: {job.ref} · model: {job.model}
                {job.started_at && ` · started: ${new Date(job.started_at).toLocaleTimeString()}`}
              </p>
              {job.diff_summary && (
                <p className="text-sm mt-2">{job.diff_summary}</p>
              )}
              {job.pull_request_url && (
                <a
                  href={job.pull_request_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-400 underline mt-1 inline-block"
                >
                  Ver PR
                </a>
              )}
              {job.error_message && (
                <p className="text-sm text-red-400 mt-1">{job.error_message.error}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
