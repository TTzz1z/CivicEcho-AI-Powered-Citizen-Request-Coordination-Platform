const password = process.env.E2E_PASSWORD

if (!password || password.length < 12) {
  throw new Error('Set E2E_PASSWORD to an isolated test password of at least 12 characters.')
}

export const e2ePassword = password
