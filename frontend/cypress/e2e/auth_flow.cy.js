describe('authentication flow', () => {
  it('signs up, logs in, and views the created profile', () => {
    const stamp = Date.now()
    const username = `rita_${stamp}`
    const email = `${username}@example.com`
    const password = 'RitaPass123!'
    const displayName = `Rita ${stamp}`
    const bio = 'Cypress authentication test user'

    cy.visit('/signup')

    cy.get('[data-testid="signup-name"]').type(displayName)
    cy.get('[data-testid="signup-bio"]').type(bio)
    cy.get('[data-testid="signup-email"]').type(email)
    cy.get('[data-testid="signup-password"]').type(password)
    cy.get('[data-testid="signup-repeat-password"]').type(password)
    cy.get('[data-testid="signup-submit"]').click()

    cy.get('[data-testid="nav-logout"]').should('be.visible').click()
    cy.get('[data-testid="logout-current-device"]').should('be.visible').click()
    cy.get('[data-testid="nav-logout"]').should('not.exist')

    cy.visit('/login')
    cy.get('[data-testid="login-email"]').type(email)
    cy.get('[data-testid="login-password"]').type(password)
    cy.get('[data-testid="login-submit"]').click()

    cy.get('[data-testid="nav-profile"]').should('be.visible').click()
    cy.url().should('include', `/profile/${username}`)
    cy.get('[data-testid="profile-name"]').should('contain', displayName)
    cy.get('[data-testid="profile-username"]').should('contain', `@${username}`)
    cy.get('[data-testid="profile-bio"]').should('contain', bio)
  })
})
