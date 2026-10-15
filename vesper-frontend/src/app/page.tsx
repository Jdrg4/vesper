import { redirect } from "next/navigation";

/** La portada es el panel; sin sesion, el middleware manda al login. */
export default function HomePage() {
  redirect("/dashboard");
}
