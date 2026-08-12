import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Ensures a component mounted in one test is fully unmounted before the next
// test runs -- without this, a stray async effect/promise from a PREVIOUS
// test's component can still fire after that test ends (see vite.config.ts's
// restoreMocks comment for the specific bug this combination caught).
afterEach(() => {
  cleanup()
})
