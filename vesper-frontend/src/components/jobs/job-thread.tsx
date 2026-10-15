"use client";

import { ExternalLink, GitBranch, Square } from "lucide-react";
import { useState } from "react";

import { BrandMark } from "@/components/ui/brand-mark";
import { Button, buttonVariants } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { type Job, jobStatus, taskLabel, triggerLabel } from "@/lib/jobs";
import { cn } from "@/lib/utils";

const NO_CHANGES = "No changes proposed.";

function duration(job: Job): string | null {
  if (!job.started_at || !job.completed_at) return null;
  const s = Math.round((Date.parse(job.completed_at) - Date.parse(job.started_at)) / 1000);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** Un job leido como conversacion: el encargo, y lo que respondio el agente. */
export function JobThread({
  job,
  repoName,
  onAbort,
}: {
  job: Job;
  repoName: string;
  onAbort: (id: string) => Promise<void> | void;
}) {
  const { active } = jobStatus(job.status);
  const took = duration(job);
  const [stopping, setStopping] = useState(false);

  async function stop() {
    setStopping(true);
    try {
      await onAbort(job.id);
    } finally {
      setStopping(false);
    }
  }

  return (
    <div role="log" aria-label="Detalle del job" className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 py-6">
      {/* El encargo, como el mensaje del usuario. */}
      <div className="flex flex-col items-end gap-2">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-card px-4 py-2.5 text-[0.9375rem] leading-relaxed shadow-raised ring-1 ring-border">
          Revisión de {taskLabel(job.task_type)} en <span className="font-medium">{repoName}</span>
          <span className="text-ink-2"> · {job.ref}</span>
        </div>
        {job.prompt && (
          <details className="group max-w-[85%] text-right">
            <summary className="cursor-pointer list-none text-xs text-ink-3 hover:text-foreground">
              Instrucciones enviadas al agente
            </summary>
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border bg-muted p-3 text-left font-mono text-xs leading-relaxed text-ink-2">
              {job.prompt}
            </pre>
          </details>
        )}
      </div>

      {/* La respuesta del agente: a todo el ancho, con su avatar. */}
      <div className="flex gap-3">
        <BrandMark size="sm" className="mt-0.5" />
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={job.status} />
            <span className="text-xs text-ink-3">
              {triggerLabel(job.trigger)} · {job.model}
              {took && ` · ${took}`}
            </span>
          </div>

          {active && (
            <div className="flex items-center gap-3">
              <p className="flex items-center gap-2 text-[0.9375rem] text-ink-2">
                {job.status === "queued" ? "En cola, esperando turno" : "Trabajando en el repo"}
                <Dots />
              </p>
              {/* Solo en marcha: el backend no aborta un job en cola, y ofrecerlo
                  haria creer que se paro uno que luego abre su PR igual. */}
              {job.status === "running" && (
                <Button variant="outline" size="sm" onClick={() => void stop()} disabled={stopping}>
                  <Square className="fill-current" />
                  {stopping ? "Deteniendo…" : "Detener"}
                </Button>
              )}
            </div>
          )}

          {job.status === "failed" && job.error_message && (
            <div
              role="alert"
              className="rounded-xl border border-destructive/30 bg-destructive-soft px-4 py-3 text-sm text-destructive"
            >
              {job.error_message.error}
            </div>
          )}

          {job.status === "needs_review" && (
            <div className="rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
              El cambio toca archivos sensibles o contiene algo con forma de secreto, así que no abrí
              el PR: revísalo tú antes.
            </div>
          )}

          {job.diff_summary &&
            (job.diff_summary === NO_CHANGES ? (
              <p className="text-[0.9375rem] leading-relaxed">
                No encontré nada que cambiar en esta revisión.
              </p>
            ) : (
              <ChangedFiles summary={job.diff_summary} />
            ))}

          {job.pull_request_url && (
            <div className="flex flex-wrap items-center gap-3">
              <a
                href={job.pull_request_url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(buttonVariants({ variant: "primary", size: "sm" }))}
              >
                Ver pull request
                <ExternalLink />
              </a>
              {job.branch_name && (
                <span className="inline-flex items-center gap-1 font-mono text-xs text-ink-3">
                  <GitBranch className="h-3.5 w-3.5" />
                  {job.branch_name}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * El backend resume el diff como "N files changed: a, b, c". Con 45 archivos ese texto
 * tapaba el boton del PR: se muestra el recuento y la lista va plegada.
 */
function ChangedFiles({ summary }: { summary: string }) {
  const m = summary.match(/^(\d+) files? changed: ([\s\S]*)$/);
  if (!m) return <p className="text-[0.9375rem] leading-relaxed">{summary}</p>;
  const count = Number(m[1]);
  const files = m[2].split(", ").filter(Boolean);
  return (
    <details className="group">
      <summary className="cursor-pointer list-none text-[0.9375rem] leading-relaxed">
        {count === 1 ? "1 archivo cambiado" : `${count} archivos cambiados`}
        <span className="ml-2 text-xs text-ink-3 group-open:hidden">Ver archivos</span>
      </summary>
      <ul className="mt-2 max-h-60 space-y-0.5 overflow-auto rounded-xl border bg-muted p-3 font-mono text-xs text-ink-2">
        {files.map((f) => (
          <li key={f} className="truncate" title={f}>
            {f}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Dots() {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      {[0, 150, 300].map((d) => (
        <span
          key={d}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60"
          style={{ animationDelay: `${d}ms` }}
        />
      ))}
    </span>
  );
}
