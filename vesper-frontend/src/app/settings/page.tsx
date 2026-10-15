"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/field";
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
      <AppShell>
        <div className="mx-auto max-w-3xl space-y-3">
          {[0, 1].map((i) => (
            <div key={i} className="h-40 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      </AppShell>
    );
  }

  if (loadError) {
    return (
      <AppShell>
        <Card className="mx-auto max-w-3xl p-8 text-center">
          <h1 className="mb-2 text-2xl font-semibold">Ajustes</h1>
          <p className="mb-4 text-muted-foreground">{loadError}</p>
          <Link href="/login" className="text-primary underline">
            Ir al login
          </Link>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ajustes</h1>
        <p className="text-sm text-muted-foreground">
          Las keys de tu proveedor de IA y los modelos que usa el agente.
        </p>
      </div>

      <section className="space-y-4">
        <h2 className="text-base font-semibold">Credenciales de IA</h2>
        <p className="text-sm text-muted-foreground">
          Vesper corre los jobs con la API key de tu propio proveedor (BYOK). La key nunca se
          vuelve a mostrar tras guardarla.
        </p>

        {credentials.length === 0 ? (
          <p className="text-sm text-muted-foreground">Todavía no hay credenciales guardadas.</p>
        ) : (
          <div className="space-y-2">
            {credentials.map((cred) => (
              <Card key={cred.id} className="flex items-center justify-between gap-3 p-4">
                <div className="min-w-0">
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
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleDeleteCredential(cred.provider_id)}
                        disabled={deletingId === cred.provider_id}
                      >
                        {deletingId === cred.provider_id ? "Eliminando..." : "Sí"}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>
                        Cancelar
                      </Button>
                    </div>
                  ) : (
                    <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(cred.provider_id)}>
                      Eliminar
                    </Button>
                  ))}
              </Card>
            ))}
          </div>
        )}

        {isAdmin && (
          <form
            onSubmit={handleSubmit(onAddCredential)}
            className="space-y-4 rounded-xl border bg-card p-5 shadow-raised"
          >
            <h3 className="text-sm font-semibold">Añadir credencial</h3>
            <div className="space-y-2">
              <Label htmlFor="provider_id">
                Proveedor
              </Label>
              <Select id="provider_id" {...register("provider_id")}>
                <option value="">Seleccionar proveedor...</option>
                {sortedProviders.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
              {errors.provider_id && (
                <p className="text-xs text-destructive">{errors.provider_id.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="api_key">
                API key
              </Label>
              <Input id="api_key" type="password" autoComplete="off" {...register("api_key")} />
              {errors.api_key && (
                <p className="text-xs text-destructive">{errors.api_key.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="label">
                Etiqueta (opcional)
              </Label>
              <Input id="label" type="text" {...register("label")} />
              {errors.label && <p className="text-xs text-destructive">{errors.label.message}</p>}
            </div>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Guardando..." : "Añadir credencial"}
            </Button>
          </form>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-base font-semibold">Modelos</h2>

        {configuredProviders.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Añade primero una API key arriba para poder elegir los modelos que usa Vesper.
          </p>
        ) : (
          <div className="space-y-4 rounded-xl border bg-card p-5 shadow-raised">
            <div className="space-y-2">
              <Label htmlFor="developer_model">
                Modelo desarrollador
              </Label>
              <Select
                id="developer_model"
                value={developerModel}
                onChange={(e) => setDeveloperModel(e.target.value)}
                disabled={!isAdmin}
              >
                {withCurrentValue(modelOptions, developerModel).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="reviewer_model">
                Modelo revisor
              </Label>
              <Select
                id="reviewer_model"
                value={reviewerModel}
                onChange={(e) => setReviewerModel(e.target.value)}
                disabled={!isAdmin}
              >
                {withCurrentValue(modelOptions, reviewerModel).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
            {isAdmin ? (
              <Button onClick={handleSaveModels} disabled={savingModels}>
                {savingModels ? "Guardando..." : "Guardar modelos"}
              </Button>
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
      </div>
    </AppShell>
  );
}
