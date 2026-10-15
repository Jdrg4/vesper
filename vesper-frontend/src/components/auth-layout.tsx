import { GitPullRequest, KeyRound, ShieldCheck } from "lucide-react";

import { BrandMark } from "@/components/ui/brand-mark";

const POINTS = [
  { icon: GitPullRequest, text: "Vigila tus repos y te abre pull requests listos para revisar." },
  { icon: KeyRound, text: "Con tu propia key: 174 proveedores de modelos, cifrada en reposo." },
  { icon: ShieldCheck, text: "Revisa cada diff en busca de secretos antes de subir nada." },
];

/**
 * Marco de login y registro. El panel de marca va siempre oscuro (como el banner del
 * README), sea cual sea el tema: es una superficie de marca, no de la interfaz.
 */
export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-[#0b1020] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-[#f5b14c] opacity-25 blur-3xl"
        />
        <div aria-hidden className="pointer-events-none absolute -bottom-32 -left-24 h-96 w-96 rounded-full bg-[#4a5be8] opacity-30 blur-3xl" />
        <div className="relative flex items-center gap-2.5">
          <BrandMark size="md" />
          <span className="text-lg font-semibold tracking-tight">Vesper</span>
        </div>
        <div className="relative max-w-md space-y-8">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight">
            Tus repos, revisados mientras duermes.
          </h2>
          <ul className="space-y-4">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex gap-3 text-[0.9375rem] leading-relaxed text-[#c9d1ff]">
                <Icon aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-[#f5b14c]" />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-[#8b93b8]">Código disponible · FSL-1.1-ALv2</p>
      </aside>

      <div className="flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex items-center gap-2.5 lg:hidden">
            <BrandMark size="md" />
            <span className="text-lg font-semibold tracking-tight">Vesper</span>
          </div>
          {children}
        </div>
      </div>
    </main>
  );
}
