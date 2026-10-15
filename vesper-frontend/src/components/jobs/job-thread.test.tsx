import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Job } from "@/lib/jobs";
import { JobThread } from "./job-thread";

const base: Job = {
  id: "j1",
  repository_id: "r1",
  task_type: "quality",
  status: "completed",
  trigger: "manual",
  ref: "main",
  model: "deepseek/deepseek-v4-pro",
  prompt: "Eres Vesper. Revisa la calidad del repo.",
  pull_request_url: null,
  branch_name: null,
  diff_summary: null,
  error_message: null,
  started_at: "2026-10-15T10:00:00Z",
  completed_at: "2026-10-15T10:01:30Z",
  created_at: "2026-10-15T10:00:00Z",
};

describe("JobThread", () => {
  it("muestra el encargo con la tarea y el repo, y las instrucciones plegadas", async () => {
    render(<JobThread job={base} repoName="acme/api" onAbort={vi.fn()} />);

    expect(screen.getByRole("log")).toHaveTextContent("Revisión de Calidad en acme/api · main");
    expect(screen.getByText("Eres Vesper. Revisa la calidad del repo.")).not.toBeVisible();
    await userEvent.click(screen.getByText("Instrucciones enviadas al agente"));
    expect(screen.getByText("Eres Vesper. Revisa la calidad del repo.")).toBeVisible();
  });

  it("con PR: resumen y enlace al pull request", () => {
    render(
      <JobThread
        job={{ ...base, diff_summary: "1 files changed: src/calc.py", pull_request_url: "https://github.com/acme/api/pull/3" }}
        repoName="acme/api"
        onAbort={vi.fn()}
      />,
    );

    expect(screen.getByText("1 archivo cambiado")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver pull request/ })).toHaveAttribute(
      "href",
      "https://github.com/acme/api/pull/3",
    );
  });

  it("fallido: el error del proveedor se lee, no se esconde", () => {
    render(
      <JobThread
        job={{ ...base, status: "failed", error_message: { error: "RuntimeError: El modelo no respondio: 403" } }}
        repoName="acme/api"
        onAbort={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("El modelo no respondio: 403");
  });

  it("en curso: indica que trabaja y permite detenerlo", async () => {
    const onAbort = vi.fn();
    render(
      <JobThread job={{ ...base, status: "running", completed_at: null }} repoName="acme/api" onAbort={onAbort} />,
    );

    expect(screen.getByText(/Trabajando en el repo/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Detener" }));
    expect(onAbort).toHaveBeenCalledWith("j1");
  });

  it("en cola no ofrece Detener: el backend solo aborta jobs en marcha", () => {
    render(
      <JobThread job={{ ...base, status: "queued", completed_at: null }} repoName="acme/api" onAbort={vi.fn()} />,
    );

    expect(screen.getByText(/En cola, esperando turno/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Detener" })).not.toBeInTheDocument();
  });

  it("Detener se desactiva mientras se procesa, para no pulsarlo varias veces", async () => {
    let resolver: () => void = () => {};
    const onAbort = vi.fn(() => new Promise<void>((r) => (resolver = r)));
    render(
      <JobThread job={{ ...base, status: "running", completed_at: null }} repoName="acme/api" onAbort={onAbort} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Detener" }));
    expect(screen.getByRole("button", { name: /Deteniendo/ })).toBeDisabled();
    resolver();
  });

  it("una lista larga de archivos no tapa el PR: recuento visible y lista plegada", () => {
    const files = Array.from({ length: 45 }, (_, i) => `src/mod${i}.py`);
    render(
      <JobThread
        job={{ ...base, diff_summary: `45 files changed: ${files.join(", ")}`, pull_request_url: "https://x/pull/1" }}
        repoName="acme/api"
        onAbort={vi.fn()}
      />,
    );

    expect(screen.getByText("45 archivos cambiados")).toBeInTheDocument();
    expect(screen.getByText("src/mod44.py")).not.toBeVisible();
  });

  it("un solo archivo se escribe en singular", () => {
    render(<JobThread job={{ ...base, diff_summary: "1 files changed: src/calc.py" }} repoName="acme/api" onAbort={vi.fn()} />);

    expect(screen.getByText("1 archivo cambiado")).toBeInTheDocument();
  });

  it("completado sin cambios lo dice en claro", () => {
    render(<JobThread job={{ ...base, diff_summary: "No changes proposed." }} repoName="acme/api" onAbort={vi.fn()} />);

    expect(screen.getByText(/No encontré nada que cambiar/)).toBeInTheDocument();
  });

  it("en marcha: cuenta qué está haciendo el agente, y cierra el stream al terminar", () => {
    const sources: FakeSource[] = [];
    class FakeSource {
      onmessage: ((e: { data: string }) => void) | null = null;
      closed = false;
      constructor(public url: string) {
        sources.push(this);
      }
      close() {
        this.closed = true;
      }
    }
    vi.stubGlobal("EventSource", FakeSource);
    const running = { ...base, status: "running" as const, completed_at: null };
    const { rerender } = render(<JobThread job={running} repoName="acme/api" onAbort={vi.fn()} />);

    expect(sources[0].url).toBe("/api/jobs/j1/events");
    act(() => sources[0].onmessage?.({ data: JSON.stringify({ event: "activity", data: { tool: "edit", path: "src/app.py" } }) }));
    expect(screen.getByText(/Editando/)).toHaveTextContent("Editando src/app.py");

    act(() => sources[0].onmessage?.({ data: JSON.stringify({ event: "activity", data: { tool: "bash", path: null } }) }));
    expect(screen.getByText(/Ejecutando un comando/)).toBeInTheDocument();

    // El evento terminal llega antes que el sondeo cambie el estado: el stream se
    // cierra ya, o EventSource reconectaria y volveria a bajar todo el historial.
    act(() => sources[0].onmessage?.({ data: JSON.stringify({ event: "completed", data: {} }) }));
    expect(sources[0].closed).toBe(true);
    expect(sources).toHaveLength(1);

    rerender(<JobThread job={{ ...running, status: "completed" }} repoName="acme/api" onAbort={vi.fn()} />);
    expect(sources[0].closed).toBe(true);
    expect(screen.queryByText(/Ejecutando un comando/)).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
