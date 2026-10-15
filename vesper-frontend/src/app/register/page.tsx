"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
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
    <main className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <h1 className="text-2xl font-semibold">Crear cuenta</h1>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {fields.map((f) => (
          <div key={f.name} className="space-y-2">
            <label htmlFor={f.name} className="text-sm font-medium">{f.label}</label>
            <input
              id={f.name}
              name={f.name}
              type={f.type}
              required
              value={(form as Record<string, string>)[f.name]}
              onChange={onChange}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
        ))}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {loading ? "Creando..." : "Crear cuenta"}
        </button>
        <p className="text-center text-sm text-muted-foreground">
          ¿Ya tienes cuenta?{" "}
          <Link href="/login" className="underline underline-offset-4">Iniciar sesión</Link>
        </p>
      </form>
    </main>
  );
}
