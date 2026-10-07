// The feed must not ask for page 2 before page 1 has arrived. Until the first page
// is in, there are no cards, so the infinite-scroll sentinel is on screen. If the
// observer already watches it, it requests page 2, page 1's reply is dropped as
// stale, and a user who has posts shows "No posts yet." (seen as a flaky E2E).
//
// When the browser reports the intersection is a matter of timing, so the spec
// replaces IntersectionObserver with one that reports "visible" at once, the worst
// case a real browser can produce.
const alwaysVisibleObserver = (win) => {
  win.IntersectionObserver = class {
    constructor(callback) { this.callback = callback }
    observe(target) { this.callback([{ isIntersecting: true, target }]) }
    unobserve() {}
    disconnect() {}
  }
}

describe('feed paging', () => {
  it('shows the first page and does not request page 2 before it', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `First page post by ${author.username}` })

      const query = { username: author.username }
      cy.intercept({ pathname: '/api/articles', query: { ...query, page: '1' } }).as('page1')
      cy.intercept({ pathname: '/api/articles', query: { ...query, page: '2' } }).as('page2')

      cy.visit(`/user-posts/${author.username}`, { onBeforeLoad: alwaysVisibleObserver })
      cy.wait('@page1')

      cy.contains('[data-testid="post-card"]', 'First page post').should('be.visible')
      cy.contains('No posts yet.').should('not.exist')
      // One post is less than a full page (10), so there is no page 2 at all.
      cy.get('@page2.all').should('have.length', 0)
    })
  })

  it('scrolling to the end loads page 2 when there is one', () => {
    cy.apiSignup().then((author) => {
      Cypress._.times(11, (i) => cy.apiCreatePost({ title: `Paged post ${i + 1}` }))

      cy.visit(`/user-posts/${author.username}`)
      cy.get('[data-testid="post-card"]').should('have.length', 10)

      cy.scrollTo('bottom')
      cy.get('[data-testid="post-card"]').should('have.length', 11)
      cy.contains('No more posts').should('be.visible')
    })
  })
})
