// Password reset: "forgot" mails a one-time link, and the link sets a new password
// and ends every session of the account. The E2E backend writes each mail to a JSON
// file (MAIL_PROVIDER=file); cy.task('lastMail', address) reads the newest one.

const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`
const NEW_PASSWORD = 'N3w-E2e-pass!'

const linkIn = (mail) => {
  const match = mail.text.match(/http:\/\/localhost:5173\/reset-password#token=[A-Za-z0-9_-]+/)
  expect(match, 'the reset link in the mail').to.not.equal(null)
  return match[0]
}

// Ask for a link through the UI, from the login page.
const requestLink = (email) => {
  cy.visit('/login')
  cy.get('[data-testid="login-forgot"]').click()
  cy.url().should('include', '/forgot-password')
  cy.get('[data-testid="forgot-email"]').type(email)
  cy.get('[data-testid="forgot-submit"]').click()
  cy.get('[data-testid="forgot-sent"]').should('contain', 'If an account uses that email')
}

const choosePassword = (password) => {
  cy.get('[data-testid="reset-password"]').type(password)
  cy.get('[data-testid="reset-repeat-password"]').type(password)
  cy.get('[data-testid="reset-submit"]').click()
}

describe('password reset', () => {
  it('mails a link that sets a new password and logs the account out everywhere', () => {
    cy.apiSignup().then((user) => {
      // The signup's session: the reset must delete it on the server, not just
      // drop the cookie, so the old value is kept and sent again afterwards.
      cy.getCookie('session_id').should('exist').then((cookie) => {
        requestLink(user.email)
        cy.task('lastMail', user.email).then((mail) => {
          expect(mail.subject).to.eq('Reset your PulseNet password')
          cy.visit(linkIn(mail))
        })
        // The token is read, then taken off the address bar.
        cy.location('hash').should('eq', '')
        choosePassword(NEW_PASSWORD)

        cy.url().should('include', '/login')
        cy.get('[data-testid="login-reset-done"]').should('be.visible')
        cy.request({ url: api('/me'), headers: { Cookie: `session_id=${cookie.value}` }, failOnStatusCode: false })
          .its('status').should('eq', 401)
      })
      cy.request({
        method: 'POST', url: api('/login'), failOnStatusCode: false,
        body: { email: user.email, password: user.password },
      }).its('status').should('eq', 401)

      cy.get('[data-testid="login-email"]').type(user.email)
      cy.get('[data-testid="login-password"]').type(NEW_PASSWORD)
      cy.get('[data-testid="login-submit"]').click()
      cy.get('[data-testid="nav-profile"]').should('be.visible')
    })
  })

  it('answers an unknown address the same way and sends nothing', () => {
    const email = `nobody_${Date.now()}@example.com`

    requestLink(email)

    cy.task('lastMail', email).should('eq', null)
  })

  it('does not take a link twice', () => {
    cy.apiSignup().then((user) => {
      cy.request('POST', api('/password/forgot'), { email: user.email })
      cy.task('lastMail', user.email).then((mail) => {
        const link = linkIn(mail)
        cy.request('POST', api('/password/reset'), { token: link.split('#token=')[1], password: NEW_PASSWORD })
        cy.visit(link)
      })
      choosePassword('An0ther-pass!')

      cy.get('[data-testid="reset-error"]').should('contain', 'invalid or has expired')
      cy.url().should('include', '/reset-password')
    })
  })

  it('says so when the link has no token, and offers a new one', () => {
    cy.visit('/reset-password')

    cy.get('[data-testid="reset-error"]').should('contain', 'incomplete')
    cy.get('[data-testid="reset-submit"]').should('not.exist')
    cy.get('[data-testid="reset-new-link"]').click()
    cy.url().should('include', '/forgot-password')
  })

  it('fits a phone screen', () => {
    cy.viewport('iphone-x')
    for (const page of ['/forgot-password', '/reset-password#token=abc']) {
      cy.visit(page)
      cy.get('form').should('be.visible')
      cy.document().then((doc) => {
        const { scrollWidth, clientWidth } = doc.documentElement
        expect(scrollWidth, `${page}: page width vs window width`).to.be.at.most(clientWidth)
      })
    }
  })
})
