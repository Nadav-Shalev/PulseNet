import { mockShell, person, viewer } from '../support/uiFixtures';

const settings = '[data-testid="nav-settings"]';
const storageKey = 'pulsenet.theme';
const expectMode = mode => cy.document().should(doc => {
  expect(doc.defaultView.getComputedStyle(doc.documentElement).colorScheme).to.equal(mode);
});
const osTheme = mode => cy.then(() => Cypress.automation('remote:debugger:protocol', {
  command: 'Emulation.setEmulatedMedia',
  params: { features: mode ? [{ name: 'prefers-color-scheme', value: mode }] : [] },
}));
const choose = mode => {
  cy.get(settings).click();
  cy.get('[data-testid="theme-' + mode + '"]').click();
  cy.get(settings).should('have.attr', 'aria-expanded', 'false');
};
function press(key, code, windowsVirtualKeyCode) {
  ['keyDown', 'keyUp'].forEach(type => {
    cy.then(() => Cypress.automation('remote:debugger:protocol', {
      command: 'Input.dispatchKeyEvent',
      params: { type, key, code, windowsVirtualKeyCode, ...(type === 'keyDown' && key === 'Enter' ? { text: '\r', unmodifiedText: '\r' } : {}) },
    }));
  });
}

describe('theme settings and branding', () => {
  beforeEach(() => {
    cy.viewport(1280, 900);
    osTheme('light');
    mockShell(viewer);
  });
  afterEach(() => osTheme(null));

  it('shows settings to guests and serves the same brand mark as the favicon', () => {
    mockShell();
    cy.visit('/about');
    cy.get('nav a').contains('PulseNet').as('brand');
    cy.get('@brand').find('img').should(img => expect(img[0].naturalWidth).to.be.greaterThan(0));
    cy.get('link[rel="icon"]').invoke('attr', 'href').then(href => {
      cy.get('@brand').find('img').should('have.attr', 'src', href);
      cy.request(href).then(response => {
        expect(response.status).to.equal(200);
        expect(response.headers['content-type']).to.include('image/svg+xml');
        expect(response.body).to.include('<svg');
      });
    });
    cy.get('@brand').click();
    cy.location('pathname').should('equal', '/');
    cy.get(settings).should('be.visible').click();
    cy.get('[role="menu"][aria-label="Settings"]').should('be.visible');
    cy.get('[role="menuitemradio"]').should('have.length', 3);
    cy.get('[data-testid="theme-system"]').should('have.attr', 'aria-checked', 'true');
    cy.get('[data-testid="settings-logout"]').should('not.exist');
    cy.get('[data-testid="theme-dark"]').click();
    expectMode('dark');
  });

  it('keeps draft input and authentication while themes persist through navigation and reload', () => {
    cy.visit('/new-post');
    cy.get('[data-testid="post-title-input"]').type('Keep this draft');
    cy.get('.ql-editor').type('Keep this body too.');
    choose('dark');
    expectMode('dark');
    cy.get('[data-testid="post-title-input"]').should('have.value', 'Keep this draft');
    cy.get('.ql-editor').should('contain', 'Keep this body too.');
    cy.get('[data-testid="nav-logout"]').should('be.visible');
    cy.contains('nav a', 'About').click();
    expectMode('dark');
    cy.reload();
    expectMode('dark');
    cy.window().its('localStorage').invoke('getItem', storageKey).should('equal', 'dark');
    choose('light');
    expectMode('light');
    cy.reload();
    expectMode('light');
    cy.get(settings).click();
    cy.get('[data-testid="theme-light"]').should('have.attr', 'aria-checked', 'true');
  });

  it('follows live OS changes in System and ignores them under explicit Light and Dark', () => {
    cy.visit('/');
    expectMode('light');
    osTheme('dark');
    cy.window().should(win => expect(win.matchMedia('(prefers-color-scheme: dark)').matches).to.equal(true));
    expectMode('dark');
    osTheme('light');
    expectMode('light');
    choose('dark');
    osTheme('dark');
    expectMode('dark');
    osTheme('light');
    expectMode('dark');
    choose('light');
    osTheme('light');
    expectMode('light');
    osTheme('dark');
    expectMode('light');
    choose('system');
    expectMode('dark');
    osTheme('light');
    expectMode('light');
    cy.window().its('localStorage').invoke('getItem', storageKey).should('equal', 'system');
  });

  it('falls back to System for an invalid stored preference', () => {
    osTheme('dark');
    cy.visit('/', { onBeforeLoad: win => win.localStorage.setItem(storageKey, 'invalid') });
    expectMode('dark');
    cy.get(settings).click();
    cy.get('[data-testid="theme-system"]').should('have.attr', 'aria-checked', 'true');
    cy.get('[data-testid="theme-light"]').click();
    expectMode('light');
    cy.window().its('localStorage').invoke('getItem', storageKey).should('equal', 'light');
  });

  it('remains usable when browser storage is unavailable', () => {
    cy.visit('/', { onBeforeLoad(win) {
      const originalRead = win.Storage.prototype.getItem;
      const originalWrite = win.Storage.prototype.setItem;
      cy.stub(win.Storage.prototype, 'getItem').callsFake(function (key) {
        if (key === storageKey) throw new win.DOMException('Storage unavailable', 'SecurityError');
        return originalRead.call(this, key);
      });
      cy.stub(win.Storage.prototype, 'setItem').callsFake(function (key, value) {
        if (key === storageKey) throw new win.DOMException('Storage unavailable', 'SecurityError');
        return originalWrite.call(this, key, value);
      });
    } });
    expectMode('light');
    osTheme('dark');
    expectMode('dark');
    choose('light');
    expectMode('light');
    choose('dark');
    expectMode('dark');
    cy.contains('nav a', 'About').click();
    expectMode('dark');
  });

  it('supports native keyboard selection, Escape, and focus return from logout confirmation', () => {
    cy.viewport(375, 850);
    cy.visit('/');
    cy.get('[data-testid="nav-profile"]').should('exist');
    cy.get(settings).focus();
    press('Enter', 'Enter', 13);
    cy.focused().should('have.attr', 'data-testid', 'theme-system');
    press('ArrowUp', 'ArrowUp', 38);
    cy.focused().should('have.attr', 'data-testid', 'theme-dark');
    press('Enter', 'Enter', 13);
    expectMode('dark');
    cy.get(settings).should('be.focused');
    press('Enter', 'Enter', 13);
    press('Escape', 'Escape', 27);
    cy.get(settings).should('be.focused');
    cy.get(settings).should(button => {
      expect(button[0].ownerDocument.defaultView.getComputedStyle(button[0]).outlineStyle).not.to.equal('none');
    });
    press('Enter', 'Enter', 13);
    press('End', 'End', 35);
    cy.focused().should('have.attr', 'data-testid', 'settings-logout');
    press('Enter', 'Enter', 13);
    cy.get('[role="dialog"]').should('be.visible').and('contain', 'Log out');
    press('Escape', 'Escape', 27);
    cy.get(settings).should('be.focused');
    press('Tab', 'Tab', 9);
    cy.focused().should('have.attr', 'aria-label', 'Open navigation menu');
  });

  [false, true].forEach(allDevices => {
    it('keeps the existing confirmation and logout contract for ' + (allDevices ? 'all devices' : 'this device'), () => {
      cy.intercept('POST', '**/api/logout', { delay: 800, body: { message: 'Logged out' } }).as('logout');
      cy.visit('/');
      cy.get('[data-testid="nav-logout"]').should('be.visible');
      choose('dark');
      cy.get(settings).click();
      cy.get('[data-testid="settings-logout"]').click();
      cy.contains('[role="dialog"] button', 'Cancel').click();
      cy.get('@logout.all').should('have.length', 0);
      cy.get(settings).should('be.focused').click();
      cy.get('[data-testid="settings-logout"]').click();
      cy.contains('[role="dialog"] button', allDevices ? 'Logout from all devices' : 'Logout from this device').click();
      cy.get('[data-testid="nav-logout"]').should('be.disabled');
      cy.get(settings).click();
      cy.get('[data-testid="settings-logout"]').should('have.attr', 'aria-disabled', 'true');
      cy.wait('@logout').its('request.body').should('deep.equal', { allDevices });
      cy.get('@logout.all').should('have.length', 1);
      cy.get('[data-testid="nav-logout"]').should('not.exist');
      cy.get('[data-testid="settings-logout"]').should('not.exist');
      cy.location('pathname').should('equal', '/');
      expectMode('dark');
    });
  });
});

describe('social profile cover', () => {
  [375, 1280].forEach(width => {
    it('overlaps the avatar without obscuring profile content at ' + width + 'px', () => {
      cy.viewport(width, 900);
      mockShell(viewer);
      cy.intercept('GET', '**/missing-avatar.png', { statusCode: 404, body: '' });
      [false, true].forEach(isAgent => {
        const profile = { ...person(2), name: 'Long profile name ' + 'unbrokenname'.repeat(7), bio: 'A long biography. '.repeat(15), profile_image: '/missing-avatar.png', is_agent: isAgent, personality: isAgent ? 'A helpful agent persona.' : null };
        cy.intercept('GET', '**/api/users/person2', profile);
        cy.visit('/profile/person2');
        cy.get('[data-testid="profile-name"]').should('have.text', profile.name);
        cy.get('[data-testid="profile-header"] .MuiAvatar-root').should('contain', 'L');
        cy.get('[data-testid="profile-header"]').should(([header]) => {
          const avatar = header.querySelector('.MuiAvatar-root').getBoundingClientRect();
          const cover = header.querySelector('[data-testid="profile-cover"]').getBoundingClientRect();
          const name = header.querySelector('[data-testid="profile-name"]').getBoundingClientRect();
          const bounds = header.getBoundingClientRect();
          // Broad proportional bounds verify overlap rather than exact CSS pixels.
          const overlap = cover.bottom - avatar.top;
          expect(overlap / avatar.height).to.be.within(0.1, 0.6);
          expect(avatar.bottom).to.be.greaterThan(cover.bottom);
          expect(avatar.left).to.be.at.least(bounds.left - 2);
          expect(avatar.right).to.be.at.most(bounds.right + 2);
          expect(bounds.bottom).to.be.greaterThan(avatar.bottom);
          if (width < 600) expect(avatar.bottom).to.be.at.most(name.top + 2);
        });
        cy.contains('button', /^Follow$/).should('be.visible');
        cy.get('[data-testid="followers-count"]').should('be.visible');
        cy.get('[data-testid="profile-agent-badge"]').should(isAgent ? 'be.visible' : 'not.exist');
        cy.get('[data-testid="profile-persona"]').should(isAgent ? 'contain' : 'not.exist', ...(isAgent ? ['A helpful agent persona.'] : []));
        cy.document().should(doc => expect(doc.documentElement.scrollWidth).to.be.at.most(doc.documentElement.clientWidth));
      });
    });
  });
});
