import { expect, test as base, type Page } from '@playwright/test'

export { expect }

type ExpectedFailure = { path: RegExp; status?: number }

export const test = base.extend<{
  expectBrowserFailure: (failure: ExpectedFailure) => void
  verifyBrowser: void
}>({
  expectBrowserFailure: async ({}, use, info) => {
    await use(failure => info.annotations.push({ type: 'expected-browser-failure', description: JSON.stringify({
      path: failure.path.source, status: failure.status,
    }) }))
  },
  verifyBrowser: [async ({ context }, use, info) => {
    const consoleErrors: Array<{ description: string; path: string }> = []
    const httpErrors: Array<{ path: string; status: number }> = []
    const errors: string[] = []
    const pathname = (url: string) => URL.canParse(url) ? new URL(url).pathname : ''
    const attach = (page: Page) => {
      page.on('console', message => {
        if (message.type() === 'error') {
          consoleErrors.push({ description: message.text(), path: pathname(message.location().url) })
        }
      })
      page.on('pageerror', error => errors.push(error.message))
    }
    context.pages().forEach(attach)
    context.on('page', attach)
    context.on('response', response => {
      if (response.status() >= 400) httpErrors.push({ path: pathname(response.url()), status: response.status() })
    })
    await use()

    const expected: ExpectedFailure[] = info.annotations.filter(annotation => annotation.type === 'expected-browser-failure')
      .map(annotation => {
        const { path, status } = JSON.parse(annotation.description!)
        return { path: new RegExp(path), status }
      })
    expect(httpErrors.filter(error => !expected.some(failure => failure.path.test(error.path) && failure.status === error.status)),
      '意外 HTTP 4xx/5xx').toEqual([])
    expect(errors.concat(consoleErrors.filter(error => !expected.some(failure => {
      if (!failure.path.test(error.path)) return false
      return failure.status === undefined ? /net::ERR_/.test(error.description) : error.description.includes(`status of ${failure.status}`)
    })).map(error => error.description)), '浏览器控制台错误').toEqual([])
  }, { auto: true }],
})
