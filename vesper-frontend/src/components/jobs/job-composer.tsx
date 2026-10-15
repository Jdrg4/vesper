"use client";

import { ArrowUp } from "lucide-react";
import { useState } from "react";

import { Select } from "@/components/ui/field";
import { TASKS } from "@/lib/jobs";
import { cn } from "@/lib/utils";

const MAX_PROMPT = 4000;

/**
 * El campo de chat de Jobs. Sin texto se lanza la plantilla de la tarea; con texto,
 * ese texto sustituye a la plantilla (prompt libre) y la tarea queda como etiqueta.
 */
export function JobComposer({
  repos,
  repoId,
  taskType,
  onRepo,
  onTask,
  onSend,
  sending,
}: {
  repos: { id: string; full_name: string }[];
  repoId: string;
  taskType: string;
  onRepo: (id: string) => void;
  onTask: (task: string) => void;
  onSend: (prompt: string | null) => Promise<boolean>;
  sending: boolean;
}) {
  const [text, setText] = useState("");
  const canSend = Boolean(repoId) && !sending;

  async function send() {
    if (!canSend) return;
    if (await onSend(text.trim() || null)) setText("");
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-2">
      <div className="flex flex-wrap gap-2">
        <Select
          aria-label="Repositorio"
          value={repoId}
          onChange={(e) => onRepo(e.target.value)}
          className="h-8 w-auto max-w-[16rem] text-xs"
        >
          <option value="">Elige un repo vigilado…</option>
          {repos.map((r) => (
            <option key={r.id} value={r.id}>
              {r.full_name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Tarea"
          value={taskType}
          onChange={(e) => onTask(e.target.value)}
          className="h-8 w-auto text-xs"
        >
          {TASKS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex items-end gap-2 rounded-3xl border bg-card px-3 py-2.5 shadow-overlay transition-all focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/10">
        <label htmlFor="job-prompt" className="sr-only">
          Instrucciones para el agente
        </label>
        <textarea
          id="job-prompt"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          maxLength={MAX_PROMPT}
          rows={1}
          placeholder={
            repoId
              ? "Dile qué hacer (opcional)…"
              : "Elige primero un repo vigilado"
          }
          className="max-h-40 flex-1 resize-none self-center bg-transparent px-2 py-1.5 text-[0.9375rem] leading-6 outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          onClick={() => void send()}
          disabled={!canSend}
          aria-label="Lanzar revisión"
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full shadow-raised transition-all",
            "bg-gradient-to-br from-primary to-star text-white hover:brightness-105 dark:text-primary-foreground",
            "disabled:opacity-30 disabled:shadow-none",
          )}
        >
          <ArrowUp className="h-[1.125rem] w-[1.125rem]" />
        </button>
      </div>
      <p className="text-center text-xs text-muted-foreground">
        Vacío usa la plantilla de la tarea
        <span className="hidden sm:inline"> · Enter para lanzar · Shift + Enter para un salto de línea</span>
      </p>
    </div>
  );
}
