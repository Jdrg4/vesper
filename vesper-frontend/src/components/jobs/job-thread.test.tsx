import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

    expect(screen.getByText("1 files changed: src/calc.py")).toBeInTheDocument();
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

  it("completado sin cambios lo dice en claro", () => {
    render(<JobThread job={{ ...base, diff_summary: "No changes proposed." }} repoName="acme/api" onAbort={vi.fn()} />);

    expect(screen.getByText(/No encontré nada que cambiar/)).toBeInTheDocument();
  });
});
