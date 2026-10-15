import "@testing-library/jest-dom/vitest";

// jsdom no implementa EventSource; el SSE de progreso del agente (F4+) lo
// mockea el test con esta clase. Por ahora el stub vacío basta para F1.
if (typeof globalThis.EventSource === "undefined") {
  class MockEventSource {
    static instances: MockEventSource[] = [];
    url: string;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    constructor(url: string) {
      this.url = url;
      MockEventSource.instances.push(this);
    }
    close() {}
  }
  globalThis.EventSource = MockEventSource as unknown as typeof EventSource;
}
