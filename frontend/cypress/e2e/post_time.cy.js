const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`
const MINUTE = 60_000

// created_at must reach the browser as one unambiguous instant (UTC with an explicit
// offset). Without the offset the browser reads the UTC value as its own local time,
// so in Israel a post written a moment ago showed "3 hours ago".
describe('post timestamps', () => {
  it('a post created a moment ago reads "just now"', () => {
    cy.apiSignup().then((user) => {
      cy.apiCreatePost({ title: `Fresh post by ${user.username}` }).then((post) => {
        // Freeze only Date in the app, at the real current time: timeAgo says "just now"
        // under 5 seconds, and a slow page load must not push it past that.
        const now = Date.now()
        cy.clock(now, ['Date'])
        cy.intercept({ method: 'GET', pathname: '/api/articles', query: { username: user.username } })
          .as('userPosts')
        cy.visit(`/user-posts/${user.username}`)

        cy.wait('@userPosts').its('response.body').then((posts) => {
          const createdAt = posts.find((p) => p.id === post.id).created_at
          expect(createdAt, 'created_at carries a UTC offset').to.match(/(Z|[+-]\d{2}:\d{2})$/)
          // The same instant the server wrote it, not one shifted by a time zone.
          expect(Math.abs(Date.parse(createdAt) - now), 'ms from now').to.be.lessThan(60_000)
        })
        cy.contains('[data-testid="post-card"]', post.title)
          .find('[data-testid="post-meta"]')
          .should('contain', 'just now')
      })
    })
  })

  // The times stay current while the page is open: one shared minute clock
  // (src/utils/clock.js) re-renders them. No reload, no request, one timer in all.
  it('moves visible posts from "32 minutes ago" to "33 minutes ago" without a reload', () => {
    cy.viewport(1280, 900)
    cy.apiSignup().then((user) => {
      const titles = [1, 2, 3].map((n) => `Clock post ${n} by ${user.username}`)
      titles.forEach((title) => cy.apiCreatePost({ title }))
      cy.request(api(`/articles?username=${user.username}`)).its('body').then((posts) => {
        const mine = posts.filter((p) => titles.includes(p.title))
        expect(mine).to.have.length(3)
        // Written last, so the posts are at most a few seconds older than it.
        cy.apiComment(mine[0].id, '<p>On the clock</p>').its('comment').then((comment) => {
          // The app's Date and interval timers, frozen 32 minutes (+5 s) after the comment.
          cy.clock(Date.parse(comment.created_at) + 32 * MINUTE + 5_000, ['Date', 'setInterval', 'clearInterval'])
          cy.intercept({ pathname: /^\/api\// }).as('api')
          cy.intercept({ method: 'GET', pathname: '/api/articles', query: { username: user.username } })
            .as('userPosts')
          cy.intercept({ method: 'GET', pathname: /^\/api\/articles\/\d+$/ }).as('body')
          let setSpy
          let clearSpy
          cy.visit(`/user-posts/${user.username}`, {
            onBeforeLoad(win) {
              // cy.clock installed its fakes first: these spies wrap them.
              setSpy = cy.spy(win, 'setInterval')
              clearSpy = cy.spy(win, 'clearInterval')
              win.sameWindow = true
            },
          })
          cy.wait('@userPosts')
          // Each card then loads its own body near the viewport: let those finish first.
          cy.wait(['@body', '@body', '@body'])
          cy.contains('Loading post body').should('not.exist')

          // Minute timers started and not cleared yet.
          const activeClocks = () => {
            const cleared = clearSpy.getCalls().map((c) => c.args[0])
            return setSpy.getCalls()
              .filter((c) => c.args[1] === MINUTE && !cleared.includes(c.returnValue))
          }
          const expectClocks = (count) => cy.wrap(null).should(() => expect(activeClocks()).to.have.length(count))
          const expectMetas = (text) => cy.get('[data-testid="post-meta"]').should(($metas) => {
            expect($metas).to.have.length(3)
            $metas.each((_, meta) => expect(meta.textContent).to.contain(text))
          })

          expectMetas('32 minutes ago')
          cy.get('@api.all').its('length').then((requests) => {
            cy.tick(MINUTE)
            expectMetas('33 minutes ago')
            cy.window().its('sameWindow').should('equal', true)           // no reload
            cy.get('@api.all').should('have.length', requests)             // no request
          })
          // Three cards, one timer (StrictMode's mount, unmount, mount in dev clears its first one).
          expectClocks(1)

          // The comment in the post's dialog follows the same clock.
          cy.contains('[data-testid="post-card"]', mine[0].title).find('[data-testid="comment-button"]').click()
          cy.contains('[data-testid="comment"]', 'On the clock').should('contain', '33 minutes ago')
          cy.tick(MINUTE)
          cy.contains('[data-testid="comment"]', 'On the clock').should('contain', '34 minutes ago')
          expectClocks(1)
          cy.get('[aria-label="Close post"]').click()

          // Leaving every timestamp behind stops the timer.
          cy.contains('nav a', 'About').click()
          cy.location('pathname').should('equal', '/about')
          expectClocks(0)
        })
      })
    })
  })
})
