import { describe, expect, it } from "vitest";

import { jobStatus, TASKS, taskLabel, triggerLabel } from "./jobs";

describe("vocabulario de jobs", () => {
  it.each([
    ["completed", "success", "Completado"],
    ["failed", "destructive", "Falló"],
    ["needs_review", "warning", "Revisar"],
    ["running", "primary", "Trabajando"],
    ["queued", "neutral", "En cola"],
  ])("el estado %s se pinta como %s (por significado, no por parecido)", (status, tone, label) => {
    expect(jobStatus(status)).toMatchObject({ tone, label });
  });

  it("un estado desconocido no hereda el significado de otro: neutro y con su texto", () => {
    expect(jobStatus("aborted")).toMatchObject({ tone: "neutral", label: "aborted" });
  });

  it("solo 'running' y 'queued' estan en curso", () => {
    expect(["queued", "running", "completed", "failed", "needs_review"].filter((s) => jobStatus(s).active)).toEqual([
      "queued",
      "running",
    ]);
  });

  it("las tareas coinciden con el enum del backend", () => {
    expect(TASKS.map((t) => t.value)).toEqual(["security", "quality", "deps", "perf", "docs"]);
    expect(taskLabel("perf")).toBe("Rendimiento");
    expect(taskLabel("nueva")).toBe("nueva");
  });

  it("traduce el disparador", () => {
    expect(triggerLabel("webhook")).toBe("Push");
    expect(triggerLabel("cron")).toBe("Programado");
  });
});
