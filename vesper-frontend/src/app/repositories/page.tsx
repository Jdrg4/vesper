"use client";

import { Lock, PlugZap, RefreshCw, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { WatchRules } from "@/components/watch-rules";
import { BrandMark } from "@/components/ui/brand-mark";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, SectionTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/field";
import { api } from "@/lib/api";

interface Installation {
  id: string;
  installation_id: number;
  installed_by: string | null;
  created_at: string;
}

interface Repo {
  id: string;
  github_id: number;
  full_name: string;
  default_branch: string;
  private: boolean;
  is_enrolled: boolean;
  tenant_id: string;
}

export default function RepositoriesPage() {
  const [install, setInstall] = useState<Installation | null>(null);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [installUrl, setInstallUrl] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  // Repo cuyo panel de reglas esta abierto. Solo uno a la vez: las reglas se
  // piden al abrirlo, no al cargar la lista.
  const [openRules, setOpenRules] = useState<string | null>(null);

  useEffect(() => {
    // Tras instalar la App, GitHub redirige aqui con ?installation_id=..&code=..
    // El `code` es lo que prueba que quien instala controla esa instalacion;
    // el backend lo canjea y rechaza el callback si no le pertenece.
    async function consumeInstallCallback() {
      const params = new URLSearchParams(window.location.search);
      const installationId = params.get("installation_id");
      const code = params.get("code");
      if (!installationId || !code) return;
      try {
        await api.post("/repositories/callback", { installation_id: Number(installationId), code });
      } catch {
        setError("No se pudo confirmar la instalación de GitHub. Reintenta desde GitHub.");
      } finally {
        // Limpiar la URL: el `code` es de un solo uso y no debe quedar en el
        // historial del navegador ni compartirse por copiar/pegar.
        window.history.replaceState({}, "", window.location.pathname);
      }
    }

    consumeInstallCallback()
      .then(() =>
        Promise.all([
          api.get("/repositories/installation"),
          api.get("/repositories"),
          api.get("/repositories/install-url"),
        ]),
      )
      .then(([instRes, reposRes, urlRes]) => {
        setInstall(instRes.data ?? null);
        setRepos(reposRes.data ?? []);
        setInstallUrl(urlRes.data?.url ?? "");
      })
      .catch(() => setError("No autenticado"))
      .finally(() => setLoading(false));
  }, []);

  async function handleSync() {
    setSyncing(true);
    setError("");
    try {
      const r = await api.post("/repositories/sync");
      setRepos(r.data ?? []);
    } catch {
      setError("Error al sincronizar. Verifica que la GitHub App esté instalada.");
    } finally {
      setSyncing(false);
    }
  }

  async function handleToggle(repo: Repo) {
    try {
      const r = await api.patch(`/repositories/${repo.id}/enroll`, null, {
        params: { enrolled: !repo.is_enrolled },
      });
      const updated: Repo = r.data;
      setRepos((prev) => prev.map((x) => (x.id === repo.id ? updated : x)));
    } catch {
      setError(`No se pudo actualizar ${repo.full_name}.`);
    }
  }

  if (loading) {
    return (
      <AppShell>
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      </AppShell>
    );
  }

  if (error && !install) {
    return (
      <AppShell>
        <Card className="p-8 text-center">
          <p className="mb-4 text-muted-foreground">{error}</p>
          <a href="/login" className="text-primary underline">
            Ir al login
          </a>
        </Card>
      </AppShell>
    );
  }

  if (!install) {
    return (
      <AppShell>
        <Card className="mx-auto flex max-w-xl flex-col items-center gap-4 px-6 py-12 text-center">
          <BrandMark size="lg" />
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">Conecta GitHub</h1>
            <p className="text-sm text-muted-foreground">
              Instala la GitHub App en los repos que quieras que Vesper vigile. Solo podrá tocar
              los que marques aquí.
            </p>
          </div>
          {installUrl ? (
            <a href={installUrl} className={buttonVariants({ variant: "primary" })}>
              <PlugZap />
              Conectar GitHub
            </a>
          ) : (
            <p className="text-sm text-muted-foreground">
              La GitHub App aún no está configurada. Contacta al administrador.
            </p>
          )}
        </Card>
      </AppShell>
    );
  }

  const q = query.trim().toLowerCase();
  const matches = (r: Repo) => !q || r.full_name.toLowerCase().includes(q);
  const enrolled = repos.filter((r) => r.is_enrolled && matches(r));
  const available = repos.filter((r) => !r.is_enrolled && matches(r));

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Repositorios</h1>
            <p className="text-sm text-muted-foreground">
              Marca qué repos vigila el agente y con qué reglas.
            </p>
          </div>
          <Button variant="outline" onClick={handleSync} disabled={syncing}>
            <RefreshCw className={syncing ? "animate-spin" : undefined} />
            {syncing ? "Sincronizando…" : "Sincronizar"}
          </Button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Buscar entre ${repos.length} repos…`}
            aria-label="Buscar repositorio"
            className="pl-9"
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <section className="space-y-3">
          <SectionTitle>
            Vigilados <span className="font-normal text-ink-3">· {enrolled.length}</span>
          </SectionTitle>
          {enrolled.length === 0 ? (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              {q ? "Ningún repo vigilado coincide con la búsqueda." : "Aún no vigilas ningún repo: elige uno abajo."}
            </Card>
          ) : (
            <div className="space-y-2">
              {enrolled.map((repo) => (
                <Card key={repo.id} className="p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-success" />
                      <div className="min-w-0">
                        <p className="truncate font-medium" title={repo.full_name}>
                          {repo.full_name}
                        </p>
                        <p className="font-mono text-xs text-ink-3">{repo.default_branch}</p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-expanded={openRules === repo.id}
                        onClick={() => setOpenRules(openRules === repo.id ? null : repo.id)}
                      >
                        {openRules === repo.id ? "Ocultar reglas" : "Reglas"}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleToggle(repo)}>
                        Dejar de vigilar
                      </Button>
                    </div>
                  </div>
                  {openRules === repo.id && (
                    <div className="mt-4 border-t pt-4">
                      <WatchRules repositoryId={repo.id} defaultBranch={repo.default_branch} />
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3">
          <SectionTitle>
            Disponibles <span className="font-normal text-ink-3">· {available.length}</span>
          </SectionTitle>
          {repos.length === 0 ? (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              No se encontraron repos. Pulsa Sincronizar.
            </Card>
          ) : available.length === 0 ? (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              {q ? "Ningún repo disponible coincide con la búsqueda." : "Ya vigilas todos tus repos."}
            </Card>
          ) : (
            <Card className="divide-y">
              {available.map((repo) => (
                <div key={repo.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium" title={repo.full_name}>
                      {repo.full_name}
                    </p>
                    <p className="flex items-center gap-1 text-xs text-ink-3">
                      {repo.private && <Lock className="h-3 w-3" aria-hidden />}
                      {repo.private ? "Privado" : "Público"} · <span className="font-mono">{repo.default_branch}</span>
                    </p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => handleToggle(repo)}>
                    Vigilar
                  </Button>
                </div>
              ))}
            </Card>
          )}
        </section>
      </div>
    </AppShell>
  );
}
