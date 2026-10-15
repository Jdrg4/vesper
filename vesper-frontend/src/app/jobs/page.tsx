"use client";

import { PanelLeft, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { JobComposer } from "@/components/jobs/job-composer";
import { JobList } from "@/components/jobs/job-list";
import { JobThread } from "@/components/jobs/job-thread";
import { BrandMark } from "@/components/ui/brand-mark";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { type Job, jobStatus, TASKS, taskLabel } from "@/lib/jobs";

interface Repo {
  id: string;
  full_name: string;
  is_enrolled: boolean;
}

const POLL_MS = 5000;
const STALE = "Se perdió la conexión o la sesión: los estados pueden estar desactualizados.";

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [repoId, setRepoId] = useState("");
  const [taskType, setTaskType] = useState("security");
  const [sending, setSending] = useState(false);
  const [drawer, setDrawer] = useState(false);
  // Varias cargas pueden solaparse (refresco automatico, lanzar, detener): solo
  // vale la ultima pedida, o una respuesta vieja borraria el job recien lanzado.
  const seq = useRef(0);
  const historyButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  const loadJobs = useCallback(async () => {
    const mine = ++seq.current;
    const r = await api.get<Job[]>("/jobs");
    if (mine === seq.current) setJobs(r.data ?? []);
  }, []);

  useEffect(() => {
    const mine = ++seq.current;
    Promise.all([api.get<Job[]>("/jobs"), api.get<Repo[]>("/repositories")])
      .then(([j, r]) => {
        if (mine === seq.current) setJobs(j.data ?? []);
        setRepos(r.data ?? []);
        // Con un solo repo vigilado no hay nada que elegir.
        const watched = (r.data ?? []).filter((x) => x.is_enrolled);
        if (watched.length === 1) setRepoId(watched[0].id);
        // El panel enlaza a /jobs?job=<id> para abrir ese job directamente.
        const wanted = new URLSearchParams(window.location.search).get("job");
        if (wanted) setActiveId(wanted);
      })
      // Un 401 tragado se veia como "no hay jobs": se dice lo que pasa.
      .catch(() => setError("No se pudieron cargar los jobs. ¿Sigue abierta la sesión?"))
      .finally(() => setLoading(false));
  }, []);

  // Mientras algo corre, la pantalla se refresca sola. Si el refresco falla se dice:
  // si no, un job terminado se quedaria "Trabajando" para siempre.
  const anyActive = jobs.some((j) => jobStatus(j.status).active);
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => {
      loadJobs()
        .then(() => setError((e) => (e === STALE ? "" : e)))
        .catch(() => setError(STALE));
    }, POLL_MS);
    return () => clearInterval(t);
  }, [anyActive, loadJobs]);

  // Cajon movil: el foco entra al abrirlo, Escape lo cierra y el foco vuelve al boton.
  useEffect(() => {
    if (!drawer) return;
    const back = historyButton.current;
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      back?.focus();
    };
  }, [drawer]);

  const repoNames = useMemo(() => Object.fromEntries(repos.map((r) => [r.id, r.full_name])), [repos]);
  const enrolled = repos.filter((r) => r.is_enrolled);
  const active = jobs.find((j) => j.id === activeId) ?? null;

  async function launch(prompt: string | null): Promise<boolean> {
    if (!repoId) return false;
    setSending(true);
    setError("");
    let created: Job;
    try {
      created = (await api.post<Job>("/jobs", { repository_id: repoId, task_type: taskType, prompt })).data;
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response?.status;
      setError(
        status === 429 ? "Has alcanzado el límite de jobs diarios de tu plan." : "No se pudo lanzar el job.",
      );
      setSending(false);
      return false;
    }
    // El job YA existe: aunque el refresco falle, no se dice "no se pudo lanzar"
    // (el usuario reintentaria y gastaria cuota con un duplicado).
    seq.current++;
    setJobs((prev) => [created, ...prev.filter((j) => j.id !== created.id)]);
    setActiveId(created.id);
    setSending(false);
    loadJobs().catch(() => setError(STALE));
    return true;
  }

  async function abort(id: string) {
    try {
      await api.post(`/jobs/${id}/abort`);
    } catch {
      setError("No se pudo detener el job.");
    }
    await loadJobs().catch(() => setError(STALE));
  }

  const list = (
    <JobList
      jobs={jobs}
      repoNames={repoNames}
      activeId={activeId}
      loading={loading}
      onSelect={(id) => {
        setActiveId(id);
        setDrawer(false);
      }}
      onNew={() => {
        setActiveId(null);
        setDrawer(false);
      }}
    />
  );

  return (
    <AppShell wide>
      <div className="flex h-[calc(100dvh-10.5rem)] min-h-[28rem] overflow-hidden rounded-2xl border bg-card shadow-raised sm:h-[calc(100dvh-8.5rem)] sm:min-h-[32rem]">
        <aside className="hidden w-72 shrink-0 overflow-y-auto border-r bg-secondary p-3 md:block">{list}</aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b bg-card/80 px-3 py-2.5 backdrop-blur sm:px-6">
            <Button
              ref={historyButton}
              variant="ghost"
              size="icon"
              className="-ml-1 h-8 w-8 md:hidden"
              onClick={() => setDrawer(true)}
              aria-label="Ver historial de jobs"
              aria-expanded={drawer}
            >
              <PanelLeft />
            </Button>
            <BrandMark size="sm" />
            <h1 className="min-w-0 flex-1 truncate text-sm font-medium">
              {active
                ? `${taskLabel(active.task_type)} · ${repoNames[active.repository_id] ?? "Repo"}`
                : "Nuevo job"}
            </h1>
            {active && <StatusBadge status={active.status} />}
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto bg-background">
            {error && (
              <p role="alert" className="mx-auto mt-4 w-full max-w-3xl px-4 text-sm text-destructive">
                {error}
              </p>
            )}
            {active ? (
              <JobThread job={active} repoName={repoNames[active.repository_id] ?? "Repo"} onAbort={abort} />
            ) : (
              <EmptyState hasRepos={enrolled.length > 0} onPick={setTaskType} taskType={taskType} />
            )}
          </div>

          <div className="border-t bg-card px-3 pb-3 pt-3 sm:px-6 sm:pb-4">
            <JobComposer
              repos={enrolled}
              repoId={repoId}
              taskType={taskType}
              onRepo={setRepoId}
              onTask={setTaskType}
              onSend={launch}
              sending={sending}
            />
          </div>
        </section>
      </div>

      {drawer && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            tabIndex={-1}
            aria-hidden
            onClick={() => setDrawer(false)}
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Historial de jobs"
            className="absolute inset-y-0 left-0 flex w-[85%] max-w-xs flex-col overflow-y-auto border-r bg-secondary p-3 shadow-overlay"
          >
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-medium">Historial</h2>
              <Button
                ref={closeButton}
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => setDrawer(false)}
                aria-label="Cerrar historial"
              >
                <X />
              </Button>
            </div>
            {list}
          </aside>
        </div>
      )}
    </AppShell>
  );
}

function EmptyState({
  hasRepos,
  taskType,
  onPick,
}: {
  hasRepos: boolean;
  taskType: string;
  onPick: (task: string) => void;
}) {
  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col items-center justify-center gap-4 px-6 py-10 text-center">
      <BrandMark size="lg" />
      <div className="space-y-1">
        <h2 className="text-2xl font-medium tracking-tight">¿Qué revisamos hoy?</h2>
        <p className="text-sm text-muted-foreground">
          {hasRepos
            ? "Elige una tarea y un repo abajo. Vesper clona el código, hace el trabajo y te abre un PR."
            : "Primero marca algún repo como vigilado en Repositorios."}
        </p>
      </div>
      <div role="group" aria-label="Tarea" className="flex flex-wrap justify-center gap-2 pt-2">
        {TASKS.map((t) => (
          <button
            key={t.value}
            type="button"
            aria-pressed={taskType === t.value}
            onClick={() => onPick(t.value)}
            className={
              taskType === t.value
                ? "rounded-full border border-primary/50 bg-primary-soft px-3.5 py-2 text-sm font-medium text-primary shadow-raised"
                : "rounded-full border bg-card px-3.5 py-2 text-sm text-ink-2 shadow-raised transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:text-foreground"
            }
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
