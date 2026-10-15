import { Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";

const SIZES = {
  sm: "h-6 w-6 [&_svg]:h-3.5 [&_svg]:w-3.5",
  md: "h-8 w-8 [&_svg]:h-4 [&_svg]:w-4",
  lg: "h-14 w-14 ring-4 ring-primary/10 [&_svg]:h-7 [&_svg]:w-7",
};

/** El agente: degradado de la marca (indigo -> dorado de la estrella). Decorativo. */
export function BrandMark({ size = "md", className }: { size?: keyof typeof SIZES; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-star text-white shadow-raised",
        SIZES[size],
        className,
      )}
    >
      <Sparkles />
    </span>
  );
}
