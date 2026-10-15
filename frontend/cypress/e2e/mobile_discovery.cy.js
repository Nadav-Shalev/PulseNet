import { mockShell, person, themeVisit, viewer } from '../support/uiFixtures';

const opener = '[data-testid="mobile-discover-open"]';
const drawer = '[data-testid="mobile-discover-drawer"]';
const sidebar = '[data-testid="home-sidebar"]';
const close = () => cy.get('[aria-label="Close discovery"]').click();

function setup() {
  mockShell(viewer);
  cy.intercept('GET', '**/api/tags/trending*', [{ name: 'react', post_count: 2 }]).as('tags');
  cy.intercept('GET', '**/api/users/suggested*', [person(2), person(3)]).as('people');
  cy.intercept('POST', '**/api/users/2/follow', { following: true }).as('follow');
  cy.intercept('GET', '**/api/users/person3', person(3));
}

function noOverflow() {
  cy.document().should(doc => expect(doc.documentElement.scrollWidth).to.be.at.most(doc.documentElement.clientWidth));
  cy.get(drawer).should(([el]) => expect(el.scrollWidth).to.be.at.most(el.clientWidth));
}

describe('mobile discovery drawer', () => {
  [375, 768].forEach(width => {
    [false, true].forEach(dark => {
      it(`loads once, follows without closing, and fits ${width}px in ${dark ? 'dark' : 'light'} mode`, () => {
        cy.viewport(width, 812);
        setup();
        themeVisit('/', dark);
        cy.get('[data-testid="post-card"]').should('be.visible');
        cy.get(sidebar).should('not.exist');
        cy.get('@tags.all').should('have.length', 0);
        cy.get('@people.all').should('have.length', 0);
        cy.get(opener).should('be.visible').click();
        cy.get(drawer).should('be.visible').and('have.attr', 'role', 'dialog');
        cy.get(drawer).find('[data-testid="trending-tags"]').should('contain', '#react');
        cy.get(drawer).find('[data-testid="who-to-follow"]').should('contain', 'Person 2');
        cy.get('.App-feed ' + sidebar).should('not.exist');
        cy.get(sidebar).should('have.length', 1);
        cy.get('[data-testid="suggested-follow"]').first().click();
        cy.wait('@follow');
        cy.get('[data-username="person2"]').should('not.exist');
        cy.get(drawer).should('be.visible');
        noOverflow();
        cy.screenshot(`discover-${width}-${dark ? 'dark' : 'light'}`, { capture: 'viewport', overwrite: true });
        close();
        cy.get(opener).should('be.focused').click();
        cy.get(drawer).should('be.visible');
        cy.get('[data-username="person2"]').should('not.exist');
        cy.get('@tags.all').should('have.length', 1);
        cy.get('@people.all').should('have.length', 1);
      });
    });
  });

  ['tag', 'profile'].forEach(destination => {
    it(`closes on ${destination} navigation and returns home closed`, () => {
      cy.viewport(375, 812);
      setup();
      cy.visit('/');
      cy.get(opener).click();
      if (destination === 'tag') cy.get('[data-testid="trending-tag"]').click();
      else cy.get(drawer).contains('a', 'Person 3').click();
      cy.location('pathname').should('eq', destination === 'tag' ? '/tag/react' : '/profile/person3');
      cy.get(drawer).should('not.exist');
      cy.go('back');
      cy.get(opener).should('be.visible').and('have.attr', 'aria-expanded', 'false');
      cy.get(sidebar).should('not.exist');
    });
  });

  it('switches at lg without duplicate sidebars or stale open state', () => {
    cy.viewport(1199, 900);
    setup();
    cy.visit('/');
    cy.get(opener).click();
    cy.get(drawer).should('be.visible');
    cy.viewport(1200, 900);
    cy.get(opener).should('not.exist');
    cy.get(drawer).should('not.exist');
    cy.get('aside ' + sidebar).should('have.length', 1).and('be.visible');
    cy.get(sidebar).should('have.length', 1);
    cy.viewport(768, 900);
    cy.get(opener).should('have.attr', 'aria-expanded', 'false');
    cy.get(sidebar).should('not.exist');
    cy.get(opener).click();
    cy.get(drawer).find(sidebar).should('have.length', 1);
  });

  [false, true].forEach(dark => {
    it(`preserves the desktop sidebar in ${dark ? 'dark' : 'light'} mode`, () => {
      cy.viewport(1280, 900);
      setup();
      themeVisit('/', dark);
      cy.get(opener).should('not.exist');
      cy.get(drawer).should('not.exist');
      cy.get(sidebar).should('have.length', 1).then(([side]) => {
        cy.get('#feed-panel').should(([feed]) => expect(side.getBoundingClientRect().left).to.be.at.least(feed.getBoundingClientRect().right));
      });
      cy.get('[data-testid="suggested-user"]').should('have.length', 2);
      cy.screenshot(`discover-desktop-${dark ? 'dark' : 'light'}`, { capture: 'viewport', overwrite: true });
    });
  });

  it('opens by keyboard, traps focus, and restores it after Escape', () => {
    cy.viewport(375, 812);
    setup();
    cy.visit('/');
    const press = (key, code, windowsVirtualKeyCode) => {
      ['keyDown', 'keyUp'].forEach(type => cy.then(() => Cypress.automation('remote:debugger:protocol', {
        command: 'Input.dispatchKeyEvent',
        params: { type, key, code, windowsVirtualKeyCode, ...(key === 'Enter' && type === 'keyDown' ? { text: '\r' } : {}) },
      })));
    };
    cy.get(opener).focus();
    press('Enter', 'Enter', 13);
    cy.get(drawer).should('be.visible');
    cy.focused().should($el => expect($el.closest(drawer).length).to.equal(1));
    cy.get('[data-testid="suggested-follow"]').last().focus();
    press('Tab', 'Tab', 9);
    cy.get('[aria-label="Close discovery"]').should('be.focused');
    press('Escape', 'Escape', 27);
    cy.get(drawer).should('not.be.visible');
    cy.get(opener).should('be.focused').and('have.attr', 'aria-expanded', 'false');
  });
});
