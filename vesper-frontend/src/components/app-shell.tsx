"use client";

import { LogOut, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { toast } from "sonner";

import { AppNav } from "@/components/app-nav";
import { BrandMark } from "@/components/ui/brand-mark";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Marco de las pantallas con sesion: cabecera fija con marca, secciones y cuenta. */
export function AppShell({
  children,
  wide = false,
}: {
  children: React.ReactNode;
  /** Jobs usa todo el ancho para sus dos columnas. */
  wide?: boolean;
}) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  async function logout() {
    try {
      await api.post("/auth/logout");
    } catch {
      // Con la cookie viva, el middleware devolveria al panel y parece que no hizo nada.
      toast.error("No se pudo cerrar la sesión. Inténtalo de nuevo.");
      return;
    }
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
        <div
          className={cn(
            "mx-auto flex w-full items-center gap-3 px-4 py-2.5 sm:px-6",
            wide ? "max-w-7xl" : "max-w-5xl",
          )}
        >
          <Link href="/dashboard" className="flex shrink-0 items-center gap-2" aria-label="Vesper, ir al panel">
            <BrandMark size="sm" />
            <span className="font-semibold tracking-tight">Vesper</span>
          </Link>
          <div className="min-w-0 flex-1">
            <div className="hidden sm:block">
              <AppNav />
            </div>
          </div>
          {/* El servidor no conoce el tema: el marcado es identico en los dos y el CSS
              (`dark:`) elige el icono. Pintarlo segun `resolvedTheme` rompia la hidratacion. */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(dark ? "light" : "dark")}
            aria-label="Cambiar entre tema claro y oscuro"
          >
            <Sun className="hidden dark:block" />
            <Moon className="dark:hidden" />
          </Button>
          <Button variant="ghost" size="icon" onClick={logout} aria-label="Cerrar sesión">
            <LogOut />
          </Button>
        </div>
      </header>
      <main
        className={cn(
          // pb-24 en movil: deja sitio a la barra de pestanas fija de abajo.
          "mx-auto w-full flex-1 px-4 pb-24 pt-6 sm:px-6 sm:py-8",
          wide ? "max-w-7xl" : "max-w-5xl",
        )}
      >
        {children}
      </main>
      <div className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
        <AppNav variant="bottom" />
      </div>
    </div>
  );
}
