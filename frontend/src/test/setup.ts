// Global test setup — runs once before all test files.
import '@testing-library/jest-dom/vitest';
import * as matchers from 'vitest-axe/matchers';
import type { AxeMatchers } from 'vitest-axe/matchers';
import { expect, afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

declare module 'vitest' {
  interface Assertion<T = any> extends AxeMatchers {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}

// Stub HTMLCanvasElement.prototype.getContext in jsdom to suppress "Not implemented" noise
if (typeof HTMLCanvasElement !== 'undefined') {
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}

expect.extend(matchers);

afterEach(() => {
  cleanup();
});
