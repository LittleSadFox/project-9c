import { vi } from "vitest";

export function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function emptyList() {
  return { items: [], total: 0 };
}

export function installFetch(handlers) {
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url);
    const method = (options.method || "GET").toUpperCase();
    const hit = handlers.find((handler) => handler.method === method && handler.test(path));
    if (hit) {
      const body = typeof hit.body === "function" ? hit.body(path, options) : hit.body;
      return jsonResponse(body, hit.status || 200);
    }
    if (path.includes("/health")) {
      return jsonResponse({ status: "ok", dev: false });
    }
    if (path.includes("/api/jobs") || path.includes("/api/boulders") || path.includes("/api/videos") || path.includes("/api/sessions") || path.includes("/api/attempts") || path.includes("/api/trash")) {
      return jsonResponse(emptyList());
    }
    return jsonResponse({});
  });
  return globalThis.fetch;
}

export function installXhr({ status = 202, payload = {}, progress = [1] } = {}) {
  const calls = [];
  class FakeXHR {
    constructor() {
      this.upload = { onprogress: null };
      this.status = status;
      this.responseText = JSON.stringify(payload);
      this.statusText = "OK";
    }

    open(method, path) {
      this.method = method;
      this.path = path;
    }

    setRequestHeader(name, value) {
      calls.push(["header", name, value]);
    }

    send(body) {
      calls.push(["send", this.method, this.path, body]);
      for (const value of progress) {
        if (this.upload.onprogress) {
          this.upload.onprogress({ lengthComputable: true, loaded: value, total: 1 });
        }
      }
      queueMicrotask(() => this.onload());
    }
  }
  globalThis.XMLHttpRequest = FakeXHR;
  return calls;
}
