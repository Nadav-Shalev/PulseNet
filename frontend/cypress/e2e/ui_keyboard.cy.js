import { mockShell, themeVisit, viewer } from '../support/uiFixtures';

// Native events exercise browser button activation and focus movement. Cypress
// 13's type('{enter}') does not perform native activation for a non-submit button.
function press(key, code, windowsVirtualKeyCode) {
  ['keyDown', 'keyUp'].forEach(type => {
    cy.then(() => Cypress.automation('remote:debugger:protocol', {
      command: 'Input.dispatchKeyEvent',
      params: { type, key, code, windowsVirtualKeyCode, ...(type === 'keyDown' && key === 'Enter' ? { text: '\r', unmodifiedText: '\r' } : {}) },
    }));
  });
}

describe('keyboard accessibility', () => {
  it('opens the menu with Enter, moves focus, and returns focus after dialogs close', () => {
    cy.viewport(375, 800);
    mockShell(viewer);
    themeVisit('/', false);
    cy.get('[data-testid="post-card"]').should('be.visible');
    cy.get('[aria-label="Open navigation menu"]').focus().should('be.focused');
    press('Enter', 'Enter', 13);
    cy.get('[aria-label="Open navigation menu"]').should('have.attr', 'aria-expanded', 'true');
    cy.get('[role="menu"]').should('be.visible');
    cy.focused().should('contain', 'Home');
    press('ArrowDown', 'ArrowDown', 40);
    cy.focused().should('contain', 'Users');
    press('Escape', 'Escape', 27);
    cy.get('[aria-label="Open navigation menu"]').should('be.focused');
    press('Tab', 'Tab', 9);
    cy.focused().should('have.attr', 'role', 'tab').and('contain', 'Global');
    cy.get('[data-testid="comment-button"]').first().focus();
    press('Enter', 'Enter', 13);
    cy.get('[role="dialog"]').should('be.visible').and('have.attr', 'aria-labelledby');
    press('Escape', 'Escape', 27);
    cy.get('[data-testid="comment-button"]').first().should('be.focused');
    cy.get('[data-testid="comment-button"]').first().should(button => {
      expect(button[0].ownerDocument.defaultView.getComputedStyle(button[0]).outlineStyle).not.to.equal('none');
    });
  });
});
