// An AI agent's profile says so (a badge) and shows its persona; a person's does
// not. The ten agents come from migration 007, which the E2E database includes.
describe('agent profile', () => {
  const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

  it('shows the AI agent badge and the persona on an agent', () => {
    cy.request(api('/users/priya_ai')).its('body').then((body) => {
      expect(body.is_agent).to.equal(true)
      expect(body.personality).to.match(/^You are Priya/)
      expect(body).not.to.have.property('email')
    })

    cy.visit('/profile/priya_ai')
    cy.get('[data-testid="profile-username"]').should('have.text', '@priya_ai')
    cy.get('[data-testid="profile-agent-badge"]').should('be.visible').and('contain', 'AI agent')
    cy.get('[data-testid="profile-persona"]').should('be.visible')
      .and('contain', 'Persona')
      .and('contain', 'You are Priya, a senior Python developer')
  })

  it('shows neither on a person', () => {
    cy.apiSignup().then((person) => {
      cy.request(api(`/users/${person.username}`)).its('body').then((body) => {
        expect(body.is_agent).to.equal(false)
        expect(body.personality).to.equal(null)
      })

      cy.visit(`/profile/${person.username}`)
      cy.get('[data-testid="profile-username"]').should('have.text', `@${person.username}`)
      cy.get('[data-testid="profile-agent-badge"]').should('not.exist')
      cy.get('[data-testid="profile-persona"]').should('not.exist')
    })
  })

  it('fits a phone screen', () => {
    cy.viewport('iphone-x')
    cy.visit('/profile/mei_ai')
    cy.get('[data-testid="profile-persona"]').should('be.visible')
    cy.document().then((doc) => {
      expect(doc.documentElement.scrollWidth).to.be.at.most(doc.documentElement.clientWidth)
    })
  })
})
