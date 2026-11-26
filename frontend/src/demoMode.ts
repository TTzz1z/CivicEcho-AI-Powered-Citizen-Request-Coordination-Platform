export const demoMode = import.meta.env.VITE_DEMO_MODE === 'true'
  || (import.meta.env.DEV && import.meta.env.VITE_DEMO_MODE === undefined)
