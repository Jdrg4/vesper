import { beforeEach, describe, expect, it, vi } from "vitest";

// El interceptor de refresh vive en axios.interceptors.response, no es una
// funcion exportada aparte. Para probarlo sin red real, se reemplaza axios
// por un mock: la instancia devuelta por axios.create() es a la vez
// invocable (para el retry `api(original)`) y expone `.post` (para el
// refresh) e `.interceptors.response.use` (para capturar el handler que
// registra src/lib/api.ts).
const { instance } = vi.hoisted(() => {
  const inst = Object.assign(vi.fn(), {
    post: vi.fn(),
    interceptors: { response: { use: vi.fn() } },
  });
  return { instance: inst };
});

vi.mock("axios", () => ({
  default: { create: vi.fn(() => instance) },
}));

interface FakeAxiosError {
  config: { url: string; _retry: boolean };
  response: { status: number };
}

type RejectedHandler = (error: FakeAxiosError) => Promise<unknown>;

async function loadOnRejected(): Promise<RejectedHandler> {
  await import("./api");
  const calls = instance.interceptors.response.use.mock.calls;
  const [, onRejected] = calls[calls.length - 1] as [unknown, RejectedHandler];
  return onRejected;
}

beforeEach(() => {
  vi.resetModules();
  instance.mockReset();
  instance.mockResolvedValue({ status: 200 });
  instance.post.mockReset();
  instance.post.mockResolvedValue({ status: 200 });
  instance.interceptors.response.use.mockClear();
});

describe("api response interceptor (refresh automatico)", () => {
  it("dedupea 401 concurrentes en UNA sola llamada a /auth/refresh y reintenta cada original", async () => {
    const onRejected = await loadOnRejected();

    const errors: FakeAxiosError[] = [
      { config: { url: "/repos", _retry: false }, response: { status: 401 } },
      { config: { url: "/jobs", _retry: false }, response: { status: 401 } },
      { config: { url: "/tenants/me", _retry: false }, response: { status: 401 } },
    ];

    await Promise.all(errors.map((e) => onRejected(e)));

    expect(instance.post).toHaveBeenCalledTimes(1);
    expect(instance.post).toHaveBeenCalledWith("/auth/refresh");

    // Cada original se reintenta con el mismo `api` instance, marcado _retry.
    expect(instance).toHaveBeenCalledTimes(3);
    for (const e of errors) {
      expect(e.config._retry).toBe(true);
    }
  });

  it("no entra en bucle si /auth/refresh devuelve 401", async () => {
    const onRejected = await loadOnRejected();

    const err: FakeAxiosError = {
      config: { url: "/auth/refresh", _retry: false },
      response: { status: 401 },
    };

    await expect(onRejected(err)).rejects.toBe(err);

    expect(instance.post).not.toHaveBeenCalled();
    expect(instance).not.toHaveBeenCalled();
  });

  it("no reintenta un request que ya fue reintentado (_retry=true)", async () => {
    const onRejected = await loadOnRejected();

    const err: FakeAxiosError = {
      config: { url: "/jobs", _retry: true },
      response: { status: 401 },
    };

    await expect(onRejected(err)).rejects.toBe(err);

    expect(instance.post).not.toHaveBeenCalled();
    expect(instance).not.toHaveBeenCalled();
  });

  it("deja pasar errores que no son 401", async () => {
    const onRejected = await loadOnRejected();

    const err = {
      config: { url: "/jobs", _retry: false },
      response: { status: 500 },
    };

    await expect(onRejected(err)).rejects.toBe(err);

    expect(instance.post).not.toHaveBeenCalled();
  });
});
