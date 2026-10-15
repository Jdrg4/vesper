"use client";

import { useEffect, useState } from "react";
import { WatchRules } from "@/components/watch-rules";
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
        await api.post("/repositories/callback", {
          installation_id: Number(installationId),
          code,
        });
      } catch {
        setError("No se pudo confirmar la instalacion de GitHub. Reintenta desde GitHub.");
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
      setRepos((prev) => prev.map((r) => (r.id === repo.id ? updated : r)));
    } catch {
      //
    }
  }

  if (loading) {
    return <main className="flex min-h-screen items-center justify-center"><p>...</p></main>;
  }

  if (error && !install) {
    return (
      <main className="min-h-screen p-8">
        <h1 className="text-2xl font-semibold mb-4">Repositorios</h1>
        <p className="text-muted-foreground mb-4">{error}</p>
        <a href="/login" className="underline">Ir al login</a>
      </main>
    );
  }

  if (!install) {
    return (
      <main className="min-h-screen p-8">
        <h1 className="text-2xl font-semibold mb-4">Repositorios</h1>
        <p className="text-muted-foreground mb-6">
          Conecta tu cuenta de GitHub para que Vesper revise tus repos.
        </p>
        {installUrl ? (
          <a
            href={installUrl}
            className="inline-block rounded-md bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground"
          >
            Conectar GitHub
          </a>
        ) : (
          <p className="text-sm text-muted-foreground">
            La GitHub App aun no esta configurada. Contacta al administrador.
          </p>
        )}
      </main>
    );
  }

  const enrolled = repos.filter((r) => r.is_enrolled);
  const available = repos.filter((r) => !r.is_enrolled);

  return (
    <main className="min-h-screen p-8 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Repositorios</h1>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="rounded-md border border-input px-4 py-2 text-sm disabled:opacity-50"
        >
          {syncing ? "Sincronizando..." : "Sync"}
        </button>
      </div>

      {enrolled.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Vigilados</h2>
          <div className="space-y-2">
            {enrolled.map((repo) => (
              <div key={repo.id} className="rounded-lg border p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{repo.full_name}</p>
                    <p className="text-xs text-muted-foreground">{repo.default_branch}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setOpenRules(openRules === repo.id ? null : repo.id)}
                      className="text-xs underline"
                    >
                      {openRules === repo.id ? "Ocultar reglas" : "Reglas"}
                    </button>
                    <button
                      onClick={() => handleToggle(repo)}
                      className="text-xs text-muted-foreground underline"
                    >
                      Dejar de vigilar
                    </button>
                  </div>
                </div>
                {openRules === repo.id && (
                  <div className="mt-3 border-t pt-3">
                    <WatchRules
                      repositoryId={repo.id}
                      defaultBranch={repo.default_branch}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {available.length > 0 && (
        <section>
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Disponibles</h2>
          <div className="space-y-2">
            {available.map((repo) => (
              <div key={repo.id} className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <p className="font-medium">{repo.full_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {repo.private ? "Privado" : "Publico"} · {repo.default_branch}
                  </p>
                </div>
                <button
                  onClick={() => handleToggle(repo)}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
                >
                  Vigilar
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {repos.length === 0 && (
        <p className="text-muted-foreground">No se encontraron repos. Haz click en Sync.</p>
      )}
    </main>
  );
}
