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
})
