"use client";

import { ArrowRight, GitPullRequest } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { BrandMark } from "@/components/ui/brand-mark";
import { buttonVariants } from "@/components/ui/button";
import { Card, SectionTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { type Job, taskLabel } from "@/lib/jobs";
import { cn } from "@/lib/utils";

interface Tenant {
  id: string;
  name: string;
  slug: string;
  plan: string;
  developer_model: string;
  reviewer_model: string;
}

interface Me {
  id: string;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
  tenant: Tenant | null;
}

interface Repo {
  id: string;
  full_name: string;
  is_enrolled: boolean;
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<Me | null>(null);
  // null = sin datos validos (cargando o error): se pinta "—", nunca un 0 falso.
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Me>("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => setError("No autenticado"));
    // Los indicadores son un extra: si fallan, el panel sigue mostrando la cuenta,
    // pero lo dice (un "0 jobs" sobre un workspace con datos seria mentir).
    api
      .get<Job[]>("/jobs")
      .then((r) => setJobs(r.data ?? []))
      .catch(() => setStatsError(true));
    api
      .get<Repo[]>("/repositories")
      .then((r) => setRepos(r.data ?? []))
      .catch(() => setStatsError(true));
  }, []);

  if (error && !user) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <div className="space-y-4 text-center">
          <p className="text-muted-foreground">{error}</p>
          <button onClick={() => router.push("/login")} className="text-primary underline">
            Ir al login
          </button>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Cargando…</p>
      </main>
    );
  }

  const today = new Date().toDateString();
  const repoNames = Object.fromEntries((repos ?? []).map((r) => [r.id, r.full_name]));
  const stats = [
    { label: "Repos vigilados", value: repos?.filter((r) => r.is_enrolled).length, href: "/repositories" },
    { label: "Jobs de hoy", value: jobs?.filter((j) => new Date(j.created_at).toDateString() === today).length, href: "/jobs" },
    { label: "PRs creados", value: jobs?.filter((j) => j.pull_request_url).length, href: "/jobs" },
    { label: "Fallidos", value: jobs?.filter((j) => j.status === "failed").length, href: "/jobs" },
  ];
  const firstName = user.full_name.split(" ")[0];

  return (
    <AppShell>
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <BrandMark size="lg" />
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Hola, {firstName}</h1>
              <p className="text-sm text-muted-foreground">Esto es lo que ha hecho Vesper en tus repos.</p>
            </div>
          </div>
          <Link href="/jobs" className={buttonVariants({ variant: "primary" })}>
            Lanzar una revisión
            <ArrowRight />
          </Link>
        </div>

        {statsError && (
          <p role="alert" className="rounded-lg bg-destructive-soft px-3 py-2 text-sm text-destructive">
            No se pudo cargar la actividad. ¿Sigue abierta la sesión?
          </p>
        )}

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {stats.map((s) => (
            <Link key={s.label} href={s.href}>
              <Card className="p-4 transition-colors hover:border-primary/40">
                <p className="text-xs text-ink-2">{s.label}</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{s.value ?? "—"}</p>
              </Card>
            </Link>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          <section className="space-y-3 lg:col-span-2">
            <div className="flex items-center justify-between">
              <SectionTitle>Actividad reciente</SectionTitle>
              <Link href="/jobs" className="text-sm text-primary hover:underline">
                Ver todo
              </Link>
            </div>
            <Card className="divide-y">
              {jobs === null ? (
                <p className="p-6 text-center text-sm text-muted-foreground">
                  {statsError ? "Sin datos de actividad." : "Cargando…"}
                </p>
              ) : jobs.length === 0 ? (
                <p className="p-6 text-center text-sm text-muted-foreground">
                  Todavía no hay jobs. Lanza el primero desde Jobs.
                </p>
              ) : (
                jobs.slice(0, 6).map((job) => (
                  <Link
                    key={job.id}
                    href={`/jobs?job=${job.id}`}
                    className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/60"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {taskLabel(job.task_type)}{" "}
                        <span className="font-normal text-ink-2">· {repoNames[job.repository_id] ?? "Repo"}</span>
                      </p>
                      <p className="text-xs text-ink-3">
                        {new Date(job.created_at).toLocaleString("es", {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                    </div>
                    {job.pull_request_url && (
                      <GitPullRequest aria-label="Tiene pull request" className="h-4 w-4 shrink-0 text-success" />
                    )}
                    <StatusBadge status={job.status} />
                  </Link>
                ))
              )}
            </Card>
          </section>

          <section className="space-y-3">
            <SectionTitle>Workspace</SectionTitle>
            <Card className="space-y-4 p-4">
              <Row label="Workspace" value={user.tenant?.name ?? "—"} hint={user.tenant?.slug} />
              <Row label="Cuenta" value={user.email} hint={user.role === "tenant_admin" ? "Administrador" : "Miembro"} />
              {user.tenant && (
                <>
                  <Row label="Modelo que desarrolla" value={user.tenant.developer_model} mono />
                  <Row label="Modelo que revisa" value={user.tenant.reviewer_model} mono />
                  <Row label="Plan" value={user.tenant.plan === "free" ? "Gratis" : user.tenant.plan} />
                </>
              )}
              <Link href="/settings" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}>
                Cambiar modelos y keys
              </Link>
            </Card>
          </section>
        </div>
      </div>
    </AppShell>
  );
}

function Row({ label, value, hint, mono }: { label: string; value: string; hint?: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-ink-2">{label}</p>
      <p className={cn("truncate text-sm font-medium", mono && "font-mono text-[0.8125rem]")} title={value}>
        {value}
      </p>
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
    </div>
  );
}
