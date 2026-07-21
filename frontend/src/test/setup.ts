import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => { cleanup() })
Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(query => ({ matches: false, media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })) })
Object.defineProperty(window, 'ResizeObserver', { writable: true, value: class { observe() {} unobserve() {} disconnect() {} } })
Object.defineProperty(Element.prototype, 'scrollIntoView', { writable: true, value: vi.fn() })
const storage = new Map<string, string>()
Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: (key:string) => storage.get(key) ?? null, setItem: (key:string, value:string) => storage.set(key, value), removeItem: (key:string) => storage.delete(key), clear: () => storage.clear() } })
