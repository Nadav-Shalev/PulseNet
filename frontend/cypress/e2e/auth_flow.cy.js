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

    cy.get('[data-testid="nav-settings"]').click()
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

  it('checks the email format before asking the server', () => {
    cy.intercept('POST', '**/api/login').as('login')
    cy.visit('/login')
    cy.get('[data-testid="login-submit"]').click()
    cy.get('[data-testid="login-error"]').should('contain', 'Email and password are required.')

    cy.get('[data-testid="login-email"]').type('not-an-email')
    cy.get('[data-testid="login-password"]').type('SomePass123!')
    cy.get('[data-testid="login-submit"]').click()
    cy.get('[data-testid="login-email-error"]').should('contain', 'Enter a valid email address')
    cy.get('[data-testid="login-email"]').should('have.attr', 'aria-invalid', 'true')
    cy.get('[data-testid="login-error"]').should('not.exist')
    cy.get('[data-testid="login-email"]').type('@example.com')               // fixing it clears the error
    cy.get('[data-testid="login-email-error"]').should('not.exist')
    cy.get('@login.all').should('have.length', 0)                             // nothing was sent
  })

  // No account enumeration: the API and the page answer a wrong password and an
  // address with no account in exactly the same way.
  it('answers a wrong password and an unknown email the same way, and offers a reset', () => {
    cy.apiSignup().then((user) => {
      cy.clearCookies()
      cy.intercept('POST', '**/api/login').as('login')
      cy.visit('/login')
      const attempt = (email, password) => {
        cy.get('[data-testid="login-email"]').clear().type(email)
        cy.get('[data-testid="login-password"]').clear().type(password)
        cy.get('[data-testid="login-submit"]').click()
        return cy.wait('@login').its('response').then((response) => {
          expect(response.statusCode).to.equal(401)
          return cy.get('[data-testid="login-auth-error"]').invoke('text').then((alert) => ({ body: response.body, alert }))
        })
      }
      attempt(user.email, 'WrongPass123!').then((wrongPassword) => {
        const unknown = `nobody_${Date.now()}@example.com`
        attempt(unknown, user.password).then((unknownEmail) => {
          expect(wrongPassword.body).to.deep.equal({ error: 'Invalid email or password' })
          expect(unknownEmail).to.deep.equal(wrongPassword)
          expect(unknownEmail.alert).to.contain('Invalid email or password. Check your details or reset your password.')

          cy.get('[data-testid="login-auth-reset"]').click()
          cy.location('pathname').should('equal', '/forgot-password')
          cy.get('[data-testid="forgot-email"]').should('have.value', unknown)
        })
      })
    })
  })
})
