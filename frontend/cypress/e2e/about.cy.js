import { mockShell, viewer } from '../support/uiFixtures';

// The About page describes the final product: its features and the real stack.
describe('about page', () => {
  it('lists the final features and the stack, and invites only guests to sign up', () => {
    cy.viewport(1280, 900);
    mockShell();
    cy.visit('/about');
    cy.get('h1').should('have.text', 'PulseNet');
    cy.get('[data-testid="about-feature"]').should('have.length.at.least', 10).then(($cards) => {
      const text = $cards.text();
      ['password', 'Following feed', 'comment', 'AI writing help', 'moderation', 'Ten AI agents',
        'Discover drawer', 'AI Activity', 'theme', 'HTTPS'].forEach((feature) => expect(text).to.contain(feature));
    });
    cy.get('[data-testid="about-stack"]').then(($stack) => {
      ['React 19', 'Vite', 'Material UI', 'Flask', 'MySQL', 'Docker Compose', 'Cypress', 'GitHub Actions']
        .forEach((tech) => expect($stack.text()).to.contain(tech));
    });
    cy.get('[data-testid="about-signup"]').should('have.attr', 'href', '/signup');

    mockShell(viewer);
    cy.visit('/about');
    cy.get('[data-testid="about-feature"]').should('exist');
    cy.get('[data-testid="nav-profile"]').should('exist');
    cy.get('[data-testid="about-signup"]').should('not.exist');
  });
});
