"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppNav } from "@/components/app-nav";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { credentialFormSchema, type CredentialFormValues } from "@/schemas/credentials";

interface ProviderModel {
  id: string;
  name: string;
}

interface Provider {
  id: string;
  name: string;
  models: ProviderModel[];
  configured: boolean;
}

interface Credential {
  id: string;
  provider_id: string;
  label: string | null;
  key_hint: string;
  last_used_at: string | null;
  created_at: string;
}

interface TenantMe {
  id: string;
  name: string;
  slug: string;
  plan: string;
  developer_model: string;
  reviewer_model: string;
  is_active: boolean;
}

interface ModelOption {
  value: string;
  label: string;
}

function buildModelOptions(configuredProviders: Provider[]): ModelOption[] {
  return configuredProviders
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .flatMap((provider) =>
      provider.models.map((model) => ({
        value: `${provider.id}/${model.id}`,
        label: `${provider.name} · ${model.name}`,
      })),
    );
}

// Si el modelo guardado en el tenant ya no corresponde a un proveedor
// configurado (p.ej. se borro la credencial), lo inyecta como opcion extra en
// vez de dejar el <select> sin coincidencia: perder ese dato silenciosamente
// haria que "Guardar" lo sobreescribiera sin que nadie lo decidiera.
function withCurrentValue(options: ModelOption[], current: string): ModelOption[] {
  if (!current || options.some((o) => o.value === current)) return options;
  return [{ value: current, label: `${current} (no disponible)` }, ...options];
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [tenant, setTenant] = useState<TenantMe | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [developerModel, setDeveloperModel] = useState("");
  const [reviewerModel, setReviewerModel] = useState("");
  const [savingModels, setSavingModels] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CredentialFormValues>({
    resolver: zodResolver(credentialFormSchema),
    defaultValues: { provider_id: "", api_key: "", label: "" },
  });

  useEffect(() => {
    Promise.all([
      api.get("/agents/providers"),
      api.get("/agents/credentials"),
      api.get("/tenants/me"),
      api.get("/auth/me"),
    ])
      .then(([providersRes, credsRes, tenantRes, meRes]) => {
        setProviders(providersRes.data ?? []);
        setCredentials(credsRes.data ?? []);
        setTenant(tenantRes.data ?? null);
        setDeveloperModel(tenantRes.data?.developer_model ?? "");
        setReviewerModel(tenantRes.data?.reviewer_model ?? "");
        setIsAdmin(meRes.data?.role === "tenant_admin");
      })
      .catch(() => setLoadError("No se pudieron cargar los ajustes."))
      .finally(() => setLoading(false));
  }, []);

  const sortedProviders = useMemo(
    () => providers.slice().sort((a, b) => a.name.localeCompare(b.name)),
    [providers],
  );
  const configuredProviders = useMemo(() => providers.filter((p) => p.configured), [providers]);
  const modelOptions = useMemo(() => buildModelOptions(configuredProviders), [configuredProviders]);

  function providerName(providerId: string): string {
    return providers.find((p) => p.id === providerId)?.name ?? providerId;
  }

  async function onAddCredential(values: CredentialFormValues) {
    try {
      const res = await api.put("/agents/credentials", {
        provider_id: values.provider_id,
        api_key: values.api_key,
        label: values.label?.trim() ? values.label.trim() : null,
      });
      const saved: Credential = res.data;
      setCredentials((prev) => [...prev.filter((c) => c.provider_id !== saved.provider_id), saved]);
      setProviders((prev) =>
        prev.map((p) => (p.id === saved.provider_id ? { ...p, configured: true } : p)),
      );
      toast.success("Credencial guardada");
      reset();
    } catch {
      toast.error("No se pudo guardar la credencial. Verifica el proveedor y la API key.");
    }
  }

  async function handleDeleteCredential(providerId: string) {
    setDeletingId(providerId);
    try {
      await api.delete(`/agents/credentials/${providerId}`);
      setCredentials((prev) => prev.filter((c) => c.provider_id !== providerId));
      setProviders((prev) => prev.map((p) => (p.id === providerId ? { ...p, configured: false } : p)));
      toast.success("Credencial eliminada");
    } catch {
      toast.error("No se pudo eliminar la credencial.");
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  }

  async function handleSaveModels() {
    setSavingModels(true);
    try {
      const res = await api.patch("/tenants/me", {
        developer_model: developerModel,
        reviewer_model: reviewerModel,
      });
      setTenant(res.data);
      toast.success("Modelos actualizados");
    } catch {
      toast.error("No se pudieron guardar los modelos.");
    } finally {
      setSavingModels(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Cargando...</p>
      </main>
    );
  }

  if (loadError) {
    return (
      <main className="min-h-screen p-8">
        <h1 className="text-2xl font-semibold mb-4">Ajustes</h1>
        <p className="text-muted-foreground mb-4">{loadError}</p>
        <Link href="/login" className="underline">
          Ir al login
        </Link>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8 max-w-3xl mx-auto space-y-10">
      <div className="space-y-4">
        <AppNav />
        <h1 className="text-2xl font-semibold">Ajustes</h1>
      </div>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Credenciales de IA</h2>
        <p className="text-sm text-muted-foreground">
          Vesper corre los jobs con la API key de tu propio proveedor (BYOK). La key nunca se
          vuelve a mostrar tras guardarla.
        </p>

        {credentials.length === 0 ? (
          <p className="text-sm text-muted-foreground">Todavía no hay credenciales guardadas.</p>
        ) : (
          <div className="space-y-2">
            {credentials.map((cred) => (
              <div
                key={cred.id}
                className="flex items-center justify-between rounded-lg border p-3"
              >
                <div>
                  <p className="font-medium">{providerName(cred.provider_id)}</p>
                  <p className="text-xs text-muted-foreground">
                    {`${cred.label ? `${cred.label} · ` : ""}••••${cred.key_hint}`}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {cred.last_used_at
                      ? `Usada por última vez: ${formatDateTime(cred.last_used_at)}`
                      : "Sin uso todavía"}
                  </p>
                </div>
                {isAdmin &&
                  (confirmDeleteId === cred.provider_id ? (
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground">¿Eliminar?</span>
                      <button
                        onClick={() => handleDeleteCredential(cred.provider_id)}
                        disabled={deletingId === cred.provider_id}
                        className="text-xs font-medium text-destructive underline disabled:opacity-50"
                      >
                        {deletingId === cred.provider_id ? "Eliminando..." : "Sí"}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="text-xs text-muted-foreground underline"
                      >
                        Cancelar
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(cred.provider_id)}
                      className="text-xs text-muted-foreground underline"
                    >
                      Eliminar
                    </button>
                  ))}
              </div>
            ))}
          </div>
        )}

        {isAdmin && (
          <form
            onSubmit={handleSubmit(onAddCredential)}
            className="space-y-3 rounded-lg border p-4"
          >
            <h3 className="text-sm font-medium">Añadir credencial</h3>
            <div className="space-y-2">
              <label htmlFor="provider_id" className="text-sm font-medium">
                Proveedor
              </label>
              <select
                id="provider_id"
                {...register("provider_id")}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="">Seleccionar proveedor...</option>
                {sortedProviders.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              {errors.provider_id && (
                <p className="text-xs text-destructive">{errors.provider_id.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <label htmlFor="api_key" className="text-sm font-medium">
                API key
              </label>
              <input
                id="api_key"
                type="password"
                autoComplete="off"
                {...register("api_key")}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              {errors.api_key && (
                <p className="text-xs text-destructive">{errors.api_key.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <label htmlFor="label" className="text-sm font-medium">
                Etiqueta (opcional)
              </label>
              <input
                id="label"
                type="text"
                {...register("label")}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              {errors.label && <p className="text-xs text-destructive">{errors.label.message}</p>}
            </div>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {isSubmitting ? "Guardando..." : "Añadir credencial"}
            </button>
          </form>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Modelos</h2>

        {configuredProviders.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Añade primero una API key arriba para poder elegir los modelos que usa Vesper.
          </p>
        ) : (
          <div className="space-y-4 rounded-lg border p-4">
            <div className="space-y-2">
              <label htmlFor="developer_model" className="text-sm font-medium">
                Modelo desarrollador
              </label>
              <select
                id="developer_model"
                value={developerModel}
                onChange={(e) => setDeveloperModel(e.target.value)}
                disabled={!isAdmin}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-50"
              >
                {withCurrentValue(modelOptions, developerModel).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label htmlFor="reviewer_model" className="text-sm font-medium">
                Modelo revisor
              </label>
              <select
                id="reviewer_model"
                value={reviewerModel}
                onChange={(e) => setReviewerModel(e.target.value)}
                disabled={!isAdmin}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-50"
              >
                {withCurrentValue(modelOptions, reviewerModel).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            {isAdmin ? (
              <button
                onClick={handleSaveModels}
                disabled={savingModels}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {savingModels ? "Guardando..." : "Guardar modelos"}
              </button>
            ) : (
              <p className="text-xs text-muted-foreground">
                Solo un administrador del workspace puede cambiar esto.
              </p>
            )}
          </div>
        )}
      </section>

      {tenant && (
        <p className="text-xs text-muted-foreground">
          Workspace: {tenant.name} · Plan: {tenant.plan}
        </p>
      )}
    </main>
  );
}
