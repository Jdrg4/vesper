import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// El componente importa `api` como instancia axios ya configurada
// (baseURL "/api", withCredentials). Se mockea el modulo entero: los tests de
// esta pagina no deben pegarle a la red ni al proxy real.
const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock }));

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastMock }));

// next/link (App Router) puede requerir el contexto del router al montarse
// fuera de una navegacion real de Next. Se sustituye por un <a> simple: la
// pagina solo lo usa para navegacion, no hay nada que probar ahi.
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import SettingsPage from "./page";

const PROVIDERS = [
  {
    id: "openai",
    name: "OpenAI",
    models: [{ id: "gpt-5", name: "GPT-5" }],
    configured: true,
  },
  {
    id: "anthropic",
    name: "Anthropic",
    models: [{ id: "claude-opus-5", name: "Claude Opus 5" }],
    configured: false,
  },
  {
    id: "opencode-go",
    name: "OpenCode Zen",
    models: [{ id: "glm-5.2", name: "GLM 5.2" }],
    configured: true,
  },
];

const CREDENTIALS = [
  {
    id: "c1",
    provider_id: "openai",
    label: "Personal",
    key_hint: "ab12",
    last_used_at: null,
    created_at: "2026-01-01T00:00:00Z",
  },
];

const TENANT = {
  id: "t1",
  name: "Acme",
  slug: "acme",
  plan: "free",
  developer_model: "openai/gpt-5",
  reviewer_model: "opencode-go/glm-5.2",
  is_active: true,
};

const ME_ADMIN = { role: "tenant_admin" };
const ME_USER = { role: "user" };

function mockLoad({
  providers = PROVIDERS,
  credentials = CREDENTIALS,
  tenant = TENANT,
  me = ME_ADMIN,
} = {}) {
  apiMock.get.mockImplementation((url: string) => {
    if (url === "/agents/providers") return Promise.resolve({ data: providers });
    if (url === "/agents/credentials") return Promise.resolve({ data: credentials });
    if (url === "/tenants/me") return Promise.resolve({ data: tenant });
    if (url === "/auth/me") return Promise.resolve({ data: me });
    return Promise.reject(new Error(`GET inesperado: ${url}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("SettingsPage", () => {
  it("los selectores de modelo solo ofrecen proveedores con configured=true", async () => {
    mockLoad();
    render(<SettingsPage />);

    const select = await screen.findByLabelText("Modelo desarrollador");
    const options = within(select).getAllByRole("option").map((o) => o.textContent);

    expect(options).toContain("OpenAI · GPT-5");
    expect(options).toContain("OpenCode Zen · GLM 5.2");
    expect(options).not.toContain("Anthropic · Claude Opus 5");
  });

  it("la API key nunca aparece en el DOM despues de guardar la credencial", async () => {
    mockLoad();
    apiMock.put.mockResolvedValue({
      data: {
        id: "c2",
        provider_id: "anthropic",
        label: null,
        key_hint: "wxyz",
        last_used_at: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    });
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByLabelText("Modelo desarrollador");

    const secretKey = "sk-super-secreta-123"; // pragma: allowlist secret
    await user.selectOptions(screen.getByLabelText("Proveedor"), "anthropic");
    await user.type(screen.getByLabelText("API key"), secretKey);

    // Mientras esta escrita, vive en el input (enmascarado por type="password").
    expect(screen.getByDisplayValue(secretKey)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Añadir credencial" }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    expect(apiMock.put).toHaveBeenCalledWith("/agents/credentials", {
      provider_id: "anthropic",
      api_key: secretKey,
      label: null,
    });

    // Tras guardar, el formulario se resetea: la key no queda en ningun input
    // ni en ningun otro nodo del DOM (la respuesta del backend solo trae
    // key_hint, nunca la key completa).
    await waitFor(() => expect(screen.queryByDisplayValue(secretKey)).not.toBeInTheDocument());
    expect(screen.queryByText(secretKey)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(secretKey);
  });

  it("muestra las credenciales guardadas con el key_hint enmascarado, nunca la key completa", async () => {
    mockLoad();
    render(<SettingsPage />);

    const hint = await screen.findByText("Personal · ••••ab12");
    expect(hint).toBeInTheDocument();
    expect(within(hint.closest("div")!).getByText("OpenAI")).toBeInTheDocument();
  });

  it("sin credenciales, explica que hay que añadir una API key en vez de mostrar los selectores", async () => {
    mockLoad({ credentials: [], providers: PROVIDERS.map((p) => ({ ...p, configured: false })) });
    render(<SettingsPage />);

    expect(
      await screen.findByText(/Añade primero una API key arriba/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Modelo desarrollador")).not.toBeInTheDocument();
  });

  it("borra una credencial tras confirmar", async () => {
    mockLoad();
    apiMock.delete.mockResolvedValue({ status: 204 });
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText("Personal · ••••ab12");
    await user.click(screen.getByRole("button", { name: "Eliminar" }));
    await user.click(screen.getByRole("button", { name: "Sí" }));

    await waitFor(() =>
      expect(apiMock.delete).toHaveBeenCalledWith("/agents/credentials/openai"),
    );
    await waitFor(() =>
      expect(screen.queryByText("Personal · ••••ab12")).not.toBeInTheDocument(),
    );
  });

  it("un usuario sin rol tenant_admin no ve el formulario de alta ni el borrado, y los selectores de modelo quedan deshabilitados", async () => {
    mockLoad({ me: ME_USER });
    render(<SettingsPage />);

    await screen.findByLabelText("Modelo desarrollador");

    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Eliminar" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Modelo desarrollador")).toBeDisabled();
    expect(screen.getByLabelText("Modelo revisor")).toBeDisabled();
  });

  it("guarda los modelos elegidos con PATCH a /tenants/me", async () => {
    mockLoad();
    apiMock.patch.mockResolvedValue({
      data: { ...TENANT, developer_model: "opencode-go/glm-5.2" },
    });
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByLabelText("Modelo desarrollador");
    await user.selectOptions(screen.getByLabelText("Modelo desarrollador"), "opencode-go/glm-5.2");
    await user.click(screen.getByRole("button", { name: "Guardar modelos" }));

    await waitFor(() =>
      expect(apiMock.patch).toHaveBeenCalledWith("/tenants/me", {
        developer_model: "opencode-go/glm-5.2",
        reviewer_model: "opencode-go/glm-5.2",
      }),
    );
  });
});
