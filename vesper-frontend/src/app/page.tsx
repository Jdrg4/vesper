import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-8 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">Vesper</h1>
      <p className="max-w-xl text-muted-foreground">
        SaaS multi-tenant que vigila tus repos GitHub y te abre PRs autónomos
        (seguridad, code quality, deps, performance, docs).
      </p>
      <div className="flex gap-4">
        <Link
          href="/login"
          className="rounded-md bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground"
        >
          Iniciar sesión
        </Link>
        <Link
          href="/register"
          className="rounded-md border border-input px-6 py-2.5 text-sm font-medium"
        >
          Crear cuenta
        </Link>
      </div>
      <p className="text-xs text-muted-foreground">Fase 2 — Auth + Multi-tenancy</p>
    </main>
  );
}
