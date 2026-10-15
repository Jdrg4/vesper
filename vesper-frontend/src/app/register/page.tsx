"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { AuthLayout } from "@/components/auth-layout";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/field";
import { api } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    email: "", password: "", full_name: "", tenant_name: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.post("/auth/register", form);
      router.push("/dashboard");
    } catch (e) {
      // 403 = la instancia tiene el registro cerrado: reintentar no sirve.
      const status = (e as { response?: { status?: number } }).response?.status;
      setError(
        status === 403
          ? "El registro está cerrado en esta instancia. Pide acceso a quien la administra."
          : "Error al registrar. Verifica los datos e intenta de nuevo.",
      );
    } finally {
      setLoading(false);
    }
  }

  const fields = [
    { name: "email", type: "email", label: "Email" },
    { name: "password", type: "password", label: "Contraseña", minLength: 8 },
    { name: "full_name", type: "text", label: "Nombre completo" },
    { name: "tenant_name", type: "text", label: "Nombre del workspace" },
  ];

  return (
    <AuthLayout>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Crear cuenta</h1>
          <p className="text-sm text-muted-foreground">Crea tu workspace y conecta tus repos.</p>
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-destructive-soft px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}
        {fields.map((f) => (
          <div key={f.name} className="space-y-2">
            <Label htmlFor={f.name}>{f.label}</Label>
            <Input
              id={f.name}
              name={f.name}
              type={f.type}
              required
              value={(form as Record<string, string>)[f.name]}
              onChange={onChange}
              minLength={f.minLength}
            />
          </div>
        ))}
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? "Creando..." : "Crear cuenta"}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          ¿Ya tienes cuenta?{" "}
          <Link href="/login" className="text-primary hover:underline">Iniciar sesión</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
