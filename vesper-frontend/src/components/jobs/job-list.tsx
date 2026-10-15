"use client";

import { SquarePen } from "lucide-react";

import { type Job, jobStatus, taskLabel, type Tone } from "@/lib/jobs";
import { cn } from "@/lib/utils";

const DOT: Record<Tone, string> = {
  success: "bg-success",
  destructive: "bg-destructive",
  warning: "bg-warning",
  primary: "bg-primary animate-pulse",
  neutral: "bg-ink-3",
};

function groupOf(iso: string): string {
  const day = new Date(iso);
  const today = new Date();
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((startOf(today) - startOf(day)) / 86_400_000);
  if (diff <= 0) return "Hoy";
  if (diff === 1) return "Ayer";
  if (diff < 7) return "Esta semana";
  return "Anteriores";
}

/** Historial de jobs, agrupado por dia, como el historial del asistente. */
export function JobList({
  jobs,
  repoNames,
  activeId,
  loading,
  onSelect,
  onNew,
}: {
  jobs: Job[];
  repoNames: Record<string, string>;
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const groups: { name: string; items: Job[] }[] = [];
  for (const job of jobs) {
    const name = groupOf(job.created_at);
    const g = groups.find((x) => x.name === name);
    if (g) g.items.push(job);
    else groups.push({ name, items: [job] });
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        onClick={onNew}
        className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2 text-sm font-medium shadow-raised transition-all hover:border-primary/40"
      >
        <SquarePen className="h-4 w-4 text-primary" />
        Nuevo job
      </button>

      {loading && (
        <div className="flex flex-col gap-1.5">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-11 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      )}

      {!loading && jobs.length === 0 && (
        <p className="px-1 py-6 text-center text-sm text-muted-foreground">Aún no hay jobs.</p>
      )}

      {groups.map((g) => (
        <div key={g.name} className="flex flex-col gap-1">
          <h3 className="px-2 pb-0.5 text-xs font-medium text-ink-3">{g.name}</h3>
          <ul className="flex flex-col gap-0.5">
            {g.items.map((job) => {
              const active = job.id === activeId;
              const repo = repoNames[job.repository_id] ?? "Repo";
              return (
                <li key={job.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(job.id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full min-w-0 items-start gap-2.5 rounded-lg px-2 py-2 text-left transition-colors",
                      active ? "bg-card shadow-raised ring-1 ring-border" : "hover:bg-card/70",
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", DOT[jobStatus(job.status).tone])}
                    />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block truncate text-sm", active ? "font-medium" : "text-foreground")}>
                        {taskLabel(job.task_type)}
                        <span className="sr-only"> · {jobStatus(job.status).label}</span>
                      </span>
                      <span className="block truncate text-xs text-ink-3" title={repo}>
                        {repo.split("/").pop()} ·{" "}
                        {new Date(job.created_at).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
