import { NextResponse } from "next/server";

// Proxy server-side de salud del backend. Útil como smoke test de que el
// frontend alcanza al backend (Cookies httpOnly + auth se validan en
// /api/*; aquí solo pasamos /health del backend).
export async function GET() {
  try {
    const r = await fetch(`${process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000"}/health`, {
      cache: "no-store",
    });
    const body = await r.json();
    return NextResponse.json(body, { status: r.status });
  } catch {
    return NextResponse.json({ status: "unavailable" }, { status: 503 });
  }
}
