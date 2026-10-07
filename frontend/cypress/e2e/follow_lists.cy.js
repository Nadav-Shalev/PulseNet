// The followers and following counts on every profile open the matching list,
// for any viewer (the lists are public), and a name in the list opens that profile.
describe('follow lists', () => {
  const openList = (kind) => {
    cy.get(`[data-testid="${kind}-count"]`).click()
    return cy.get('[data-testid="follow-list-dialog"]').should('be.visible')
  }

  it("shows another user's followers and following, and links to each profile", () => {
    cy.apiSignup().then((author) => {
      // apiSignup logs in as the new user, so the reader is the one who follows.
      cy.apiSignup().then((reader) => {
        cy.apiFollow(author.id)

        cy.visit(`/profile/${author.username}`)
        cy.get('[data-testid="followers-count"]').should('contain', '1 follower')

        openList('followers').within(() => {
          cy.contains('Followers')
          cy.get('[data-testid="follow-list-item"]').should('have.length', 1)
            .and('contain', `@${reader.username}`)
            .click()
        })
        cy.location('pathname').should('eq', `/profile/${reader.username}`)
        cy.get('[data-testid="follow-list-dialog"]').should('not.exist')
        cy.get('[data-testid="profile-username"]').should('have.text', `@${reader.username}`)

        // The reader's own profile: the following list holds the author.
        openList('following').within(() => {
          cy.contains('Following')
          cy.get('[data-testid="follow-list-item"]').should('contain', `@${author.username}`)
        })
        cy.get('body').type('{esc}')
        cy.get('[data-testid="follow-list-dialog"]').should('not.exist')

        openList('followers').within(() => {
          cy.get('[data-testid="follow-list-empty"]').should('have.text', 'You have no followers yet.')
        })
      })
    })
  })

  it('works for a logged-out visitor too', () => {
    cy.apiSignup().then((author) => {
      cy.apiSignup().then((reader) => {
        cy.apiFollow(author.id)
        cy.clearCookies()

        cy.visit(`/profile/${author.username}`)
        openList('followers').within(() => {
          cy.get('[data-testid="follow-list-item"]').should('contain', `@${reader.username}`)
        })
        cy.get('[aria-label="Close"]').click()

        openList('following').within(() => {
          cy.get('[data-testid="follow-list-empty"]')
            .should('have.text', `@${author.username} is not following anyone yet.`)
        })
      })
    })
  })
})
