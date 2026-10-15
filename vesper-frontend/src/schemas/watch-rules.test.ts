import { describe, expect, it } from "vitest";
import {
  cronFromPreset,
  presetFromCron,
  watchRuleSchema,
} from "@/schemas/watch-rules";

const BASE = {
  id: "0d1b1e6e-0000-4000-8000-000000000001",
  repository_id: "0d1b1e6e-0000-4000-8000-000000000002",
  task_type: "security" as const,
  cron: null,
  on_push: true,
  ref: null,
  enabled: true,
  next_run_at: null,
  last_run_at: null,
  created_at: "2026-08-03T00:00:00Z",
};

describe("watchRuleSchema", () => {
  it("acepta una regla solo con on_push", () => {
    expect(watchRuleSchema.parse(BASE).on_push).toBe(true);
  });

  it("acepta una regla con cadencia y proxima ejecucion", () => {
    const r = watchRuleSchema.parse({
      ...BASE,
      cron: "0 3 * * *",
      on_push: false,
      next_run_at: "2026-08-04T03:00:00Z",
    });
    expect(r.cron).toBe("0 3 * * *");
  });

  it("rechaza un task_type que el backend no conoce", () => {
    expect(() => watchRuleSchema.parse({ ...BASE, task_type: "refactor" })).toThrow();
  });
});

describe("presets de cadencia", () => {
  it("mapea los presets a expresiones cron", () => {
    expect(cronFromPreset("daily")).toBe("0 3 * * *");
    expect(cronFromPreset("weekly")).toBe("0 3 * * 1");
    expect(cronFromPreset("hourly")).toBe("0 * * * *");
  });

  it("sin cadencia y personalizado no aportan expresion", () => {
    expect(cronFromPreset("none")).toBeNull();
    expect(cronFromPreset("custom")).toBeNull();
  });

  it("reconoce la expresion guardada", () => {
    expect(presetFromCron("0 3 * * 1")).toBe("weekly");
    expect(presetFromCron(null)).toBe("none");
  });

  it("una expresion que no casa con ningun preset es personalizada", () => {
    expect(presetFromCron("15 7 * * 3")).toBe("custom");
  });
});
