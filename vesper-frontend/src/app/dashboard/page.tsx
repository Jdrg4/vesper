"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { api } from "@/lib/api";

interface Tenant {
  id: string; name: string; slug: string; plan: string;
  developer_model: string; reviewer_model: string;
}

interface Me {
  id: string; email: string; full_name: string; role: string;
  tenant_id: string; tenant: Tenant | null;
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<Me | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/auth/me").then((r) => setUser(r.data)).catch(() => setError("No autenticado"));
  }, []);

  async function handleLogout() {
    await api.post("/auth/logout");
    router.push("/login");
  }

  if (error && !user) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <div className="space-y-4 text-center">
          <p className="text-muted-foreground">{error}</p>
          <button onClick={() => router.push("/login")} className="underline">
            Ir al login
          </button>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Cargando...</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Vesper</h1>
          <button onClick={handleLogout} className="text-sm text-muted-foreground underline">
            Salir
          </button>
        </div>
        <AppNav />
        <div className="rounded-lg border p-4 space-y-3">
          <div>
            <span className="text-xs text-muted-foreground">Workspace</span>
            <p className="font-medium">{user.tenant?.name ?? "—"}</p>
            <p className="text-sm text-muted-foreground">{user.tenant?.slug}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">Usuario</span>
            <p className="font-medium">{user.full_name}</p>
            <p className="text-sm text-muted-foreground">{user.email} · {user.role}</p>
          </div>
          {user.tenant && (
            <div>
              <span className="text-xs text-muted-foreground">Modelos IA</span>
              <p className="text-sm">Developer: {user.tenant.developer_model}</p>
              <p className="text-sm">Reviewer: {user.tenant.reviewer_model}</p>
              <p className="text-xs text-muted-foreground">Plan: {user.tenant.plan}</p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
