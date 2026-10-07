// Smoke test for the shared api* commands (cypress/support/commands.js): state they
// create through the backend must be what the UI then shows.
describe('shared API commands', () => {
  it('apiSignup + apiCreatePost: the post appears on the author page', () => {
    cy.apiSignup().then((user) => {
      cy.apiCreatePost({ title: `Hello from ${user.username}`, tags: ['e2e'] }).then((post) => {
        expect(post.id).to.be.a('number')

        cy.visit(`/user-posts/${user.username}`)
        cy.contains(post.title).should('be.visible')
      })
    })
  })

  it('apiLogin: the app picks up the session it creates', () => {
    cy.apiSignup().then((user) => {
      cy.clearAllCookies()
      cy.visit('/')
      cy.get('[data-testid="nav-logout"]').should('not.exist')

      cy.apiLogin(user)
      cy.visit('/')
      cy.get('[data-testid="nav-profile"]').should('be.visible').click()
      cy.url().should('include', `/profile/${user.username}`)
    })
  })
})
