"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { AuthLayout } from "@/components/auth-layout";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/field";
import { api } from "@/lib/api";
import { safeNextPath } from "@/lib/safe-next";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.post("/auth/login", { email, password });
      // El middleware manda aqui con `?next=` la ruta que se pedia. Se lee de
      // `window.location` y no con `useSearchParams` para no obligar a envolver
      // la pagina en un Suspense. `safeNextPath` solo deja pasar rutas del
      // mismo origen: un `next` con host ajeno convertiria el login en un
      // redirector abierto.
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(safeNextPath(next, window.location.origin));
    } catch {
      setError("Credenciales inválidas o error de conexión");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Iniciar sesión</h1>
          <p className="text-sm text-muted-foreground">Entra para ver qué ha hecho el agente.</p>
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-destructive-soft px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Contraseña</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? "Entrando..." : "Entrar"}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          ¿No tienes cuenta?{" "}
          <Link href="/register" className="text-primary hover:underline">Registrarse</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
