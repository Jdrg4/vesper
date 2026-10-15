import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-xl border bg-card shadow-raised", className)} {...props} />;
}

/** Titulo de seccion dentro de una pagina: frase normal, sin versalitas decorativas. */
export function SectionTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-sm font-semibold text-foreground", className)} {...props} />;
}
