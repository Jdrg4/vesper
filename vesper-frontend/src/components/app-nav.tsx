"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SECTIONS = [
  { href: "/dashboard", label: "Panel" },
  { href: "/repositories", label: "Repositorios" },
  { href: "/jobs", label: "Jobs" },
  { href: "/settings", label: "Ajustes" },
];

/** Navegacion comun de las pantallas con sesion. */
export function AppNav() {
  // `string | null`: fuera del App Router (tests de pagina) llega null.
  const pathname = usePathname() ?? "";
  return (
    <nav aria-label="Secciones" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {SECTIONS.map(({ href, label }) => {
        const current = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={current ? "font-medium text-foreground" : "text-muted-foreground underline"}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
