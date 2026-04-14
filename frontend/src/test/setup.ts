import '@testing-library/jest-dom/vitest';

// Fix jsdom AbortSignal incompatibility with Node's native fetch/Request
// react-router uses `new Request(url, { signal })` internally, and jsdom's
// AbortSignal doesn't satisfy Node's native type check.
const originalRequest = globalThis.Request;
globalThis.Request = class extends originalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init?.signal) {
      const { signal: _signal, ...rest } = init;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
} as typeof Request;
