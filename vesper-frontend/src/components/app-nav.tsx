"use client";

import { FolderGit2, LayoutDashboard, Settings, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "/dashboard", label: "Panel", icon: LayoutDashboard },
  { href: "/repositories", label: "Repositorios", icon: FolderGit2 },
  { href: "/jobs", label: "Jobs", icon: Sparkles },
  { href: "/settings", label: "Ajustes", icon: Settings },
];

/**
 * Navegacion comun de las pantallas con sesion. `top` en pantallas anchas; `bottom`
 * es la barra de pestanas del movil: arriba no caben las cuatro secciones en 390 px
 * y "Ajustes" quedaba fuera de la pantalla.
 */
export function AppNav({ variant = "top" }: { variant?: "top" | "bottom" }) {
  // `string | null`: fuera del App Router (tests de pagina) llega null.
  const pathname = usePathname() ?? "";

  if (variant === "bottom") {
    return (
      <nav aria-label="Secciones" className="grid grid-cols-4">
        {SECTIONS.map(({ href, label, icon: Icon }) => {
          const current = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={current ? "page" : undefined}
              className={cn(
                "flex flex-col items-center gap-0.5 py-2 text-[0.6875rem] font-medium transition-colors",
                current ? "text-primary" : "text-ink-2",
              )}
            >
              <Icon aria-hidden className="h-5 w-5" />
              {label}
            </Link>
          );
        })}
      </nav>
    );
  }

  return (
    <nav aria-label="Secciones" className="flex items-center gap-1">
      {SECTIONS.map(({ href, label }) => {
        const current = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "shrink-0 rounded-lg px-3 py-1.5 text-sm transition-colors",
              current
                ? "bg-card font-medium text-foreground shadow-raised ring-1 ring-border"
                : "text-ink-2 hover:bg-card/70 hover:text-foreground",
            )}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
