import { article, mockShell, person, viewer } from '../support/uiFixtures';

const card = '[data-testid="post-card"]';
const body = '[data-testid="post-body"]';
const toggle = '[data-testid="post-body-toggle"]';
const longHtml = '<p><a href="/about">Visible link</a> and <strong>clear emphasis</strong>.</p>'
  + '<p>Thoughtful software makes everyday tasks easier to understand.</p>'.repeat(10)
  + '<ul><li>A useful list item</li></ul><pre><code>const readable = true;</code></pre>'
  + '<p><a href="/users">Last link</a></p>';
const setBody = (html, options = {}) => cy.intercept('GET', '**/api/articles/1', { body: { ...article(1), body_html: html }, ...options });
const press = (key, code, windowsVirtualKeyCode) => {
  ['keyDown', 'keyUp'].forEach(type => cy.then(() => Cypress.automation('remote:debugger:protocol', {
    command: 'Input.dispatchKeyEvent',
    params: { type, key, code, windowsVirtualKeyCode, ...(type === 'keyDown' && key === 'Enter' ? { text: '\r', unmodifiedText: '\r' } : {}) },
  })));
};

describe('inline post bodies', () => {
  beforeEach(() => { cy.viewport(1280, 900); mockShell(viewer); });

  it('expands and collapses intact rich text in the same card without navigation or another request', () => {
    setBody(longHtml).as('detail');
    cy.visit('/');
    cy.get(toggle).should('have.text', 'Read More').and('have.attr', 'aria-expanded', 'false');
    cy.get(body + ' .rich-text').should('contain', 'Last link');
    cy.get(toggle).click().should('have.text', 'Read Less').and('have.attr', 'aria-expanded', 'true');
    cy.get(body + ' .rich-text').invoke('html').should('equal', longHtml);
    cy.get(body + ' strong').should('be.visible');
    cy.get(body + ' li').should('be.visible');
    cy.get(body + ' pre').should('be.visible');
    cy.get('[data-testid="like-count"]').should('have.text', '4');
    cy.get('[data-testid="report-post"]').should('exist');
    cy.get('[data-testid="comment-button"]').should('exist');
    cy.get(toggle).click().should('have.text', 'Read More').and('be.focused');
    cy.get(body + ' .rich-text').should(content => {
      const clip = content[0].parentElement;
      expect(clip.scrollHeight).to.be.greaterThan(clip.clientHeight);
      expect(content[0].ownerDocument.defaultView.getComputedStyle(clip).webkitLineClamp, 'three actual lines').to.equal('3');
    });
    cy.location('pathname').should('equal', '/');
    cy.get('[data-testid="post-dialog"]').should('not.exist');
    cy.get('@detail.all').should('have.length', 1);
    cy.get('[data-testid="comment-button"]').click();
    cy.get('[data-testid="post-dialog"] .rich-text').first().invoke('html').should('equal', longHtml);
    cy.get('@detail.all').should('have.length', 1);
  });

  it('shows short formatted and empty bodies fully without expansion controls', () => {
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, [article(1), article(2)]);
    setBody('<p>Short <strong>formatted</strong> text.</p>');
    cy.intercept('GET', '**/api/articles/2', { ...article(2), body_html: '' });
    cy.visit('/');
    cy.get(body + ' .rich-text').should('have.length', 2);
    cy.get(body + ' strong').should('be.visible').and('have.text', 'formatted');
    cy.get(body + ' .rich-text').last().should('be.empty');
    cy.get(toggle).should('not.exist');
  });

  it('updates truncation after a resize while preserving the full HTML', () => {
    const html = '<p>' + 'Some text. '.repeat(18) + '</p>';
    setBody(html);
    cy.visit('/');
    cy.get(body + ' .rich-text').should('contain', 'Some text.');
    cy.get(toggle).should('not.exist');
    cy.viewport(375, 900);
    cy.get(toggle).should('have.text', 'Read More').click();
    cy.get(body + ' .rich-text').invoke('html').should('equal', html);
    cy.get(toggle).should('have.text', 'Read Less').click();
    cy.viewport(1280, 900);
    cy.get(toggle).should('not.exist');
    cy.get(body + ' .rich-text').invoke('html').should('equal', html);
  });

  it('defers distant cards and shares a pending request with Comments', () => {
    cy.viewport(375, 550);
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, Array.from({ length: 6 }, (_, i) => article(i + 1)));
    setBody(longHtml, { delay: 700 }).as('first');
    cy.intercept('GET', '**/api/articles/6', { ...article(6), body_html: longHtml }).as('distant');
    cy.visit('/user-posts/person2');
    cy.get(body).first().should('contain', 'Loading post body...');
    cy.get('@distant.all').should('have.length', 0);
    cy.get('[data-testid="comment-button"]').first().click();
    cy.get('[aria-label="Loading post"]').should('be.visible');
    cy.wait('@first');
    cy.get('[data-testid="post-dialog"]').should('contain', 'A useful list item');
    cy.get('@first.all').should('have.length', 1);
    cy.get('[aria-label="Close post"]').click();
    cy.get(card).last().scrollIntoView();
    cy.get(card).last().find(toggle).should('exist');
    cy.get('@distant.all').should('have.length', 1);
  });

  it('retains the excerpt on failure and retries once without automatically looping', () => {
    let calls = 0;
    cy.intercept('GET', '**/api/articles/1', req => req.reply(++calls === 1
      ? { statusCode: 503, body: { error: 'Body unavailable' } }
      : { delay: 500, body: { ...article(1), body_html: longHtml } }));
    cy.visit('/');
    cy.get(body).should('contain', article(1).description).and('contain', 'Body unavailable');
    cy.get(toggle).should('not.exist');
    cy.viewport(768, 900);
    cy.get(body).contains('button', 'Retry').click();
    cy.get(body).contains('button', 'Retry').should('not.exist');
    cy.get(body).should('contain', 'Loading post body...');
    cy.get(toggle).should('have.text', 'Read More');
    cy.get(body).should('not.contain', 'Body unavailable');
    cy.then(() => expect(calls).to.equal(2));
  });

  it('ignores an old detail response after changing feeds', () => {
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, req => req.reply(
      req.query.feed === 'following' ? [article(2, 'Following card')] : [article(1, 'Global card')]));
    cy.intercept('GET', '**/api/articles/1', { delay: 1000, body: { ...article(1), body_html: '<p>Stale body</p>' } }).as('oldBody');
    cy.intercept('GET', '**/api/articles/2', { ...article(2), body_html: '<p>Current body</p>' });
    cy.visit('/');
    cy.get(body).should('contain', 'Loading post body...');
    cy.contains('[role="tab"]', 'Following').click();
    cy.get(body).should('contain', 'Current body');
    cy.wait('@oldBody');
    cy.get(card).should('have.length', 1).and('contain', 'Following card').and('not.contain', 'Stale body');
  });

  it('falls back safely when the browser does not provide the body observers', () => {
    setBody('<p>' + 'Some text. '.repeat(18) + '</p>').as('detail');
    cy.visit('/', { onBeforeLoad(win) { win.IntersectionObserver = undefined; win.ResizeObserver = undefined; } });
    cy.wait('@detail');
    cy.get(body + ' .rich-text').should('exist');
    cy.get(toggle).should('not.exist');
    cy.viewport(375, 900);
    cy.get(toggle).should('have.text', 'Read More').click().should('have.text', 'Read Less');
    cy.get('[aria-label="Open navigation menu"]').click();
    cy.contains('#mobile-navigation a', 'About').click();
    cy.location('pathname').should('equal', '/about');
    cy.viewport(768, 900);
  });

  it('supports keyboard toggling and restores clipped links when expanded', () => {
    setBody(longHtml);
    cy.visit('/');
    cy.get(toggle).should('exist');
    cy.contains(body + ' a', 'Last link').should('have.attr', 'tabindex', '-1');
    cy.contains(body + ' a', 'Visible link').focus();
    press('Tab', 'Tab', 9);
    cy.get(toggle).should('be.focused').and('have.attr', 'aria-controls');
    press('Enter', 'Enter', 13);
    cy.get(toggle).should('be.focused').and('have.text', 'Read Less');
    cy.contains(body + ' a', 'Last link').should('be.visible').and('not.have.attr', 'tabindex');
    press('Enter', 'Enter', 13);
    cy.get(toggle).should('be.focused').and('have.text', 'Read More');
    cy.contains(body + ' a', 'Last link').should('have.attr', 'tabindex', '-1');
  });
});

describe('vertical feeds and compact discovery', () => {
  [375, 768, 1280].forEach(width => {
    it('stacks every feed and preserves sidebar placement at ' + width + 'px', () => {
      cy.viewport(width, 900);
      mockShell(viewer);
      cy.intercept({ method: 'GET', pathname: '/api/articles' }, [article(1), article(2)]);
      cy.intercept('GET', '**/api/users/person2', { ...person(2), bio: 'A profile' });
      const stacked = () => {
        cy.get(card).should('have.length', 2).should(([first, second]) => {
          const a = first.getBoundingClientRect(), b = second.getBoundingClientRect();
          expect(Math.abs(a.left - b.left)).to.be.at.most(2);
          expect(Math.abs(a.width - b.width)).to.be.at.most(2);
          expect(b.top).to.be.at.least(a.bottom - 1);
          if (width === 375) expect(a.width).to.be.greaterThan(width - 64);
        });
        cy.document().should(doc => expect(doc.documentElement.scrollWidth).to.be.at.most(doc.documentElement.clientWidth));
      };
      cy.visit('/');
      stacked();
      cy.get('[data-testid="home-sidebar"]').then(([side]) => cy.get(card).first().should(([post]) => {
        const a = side.getBoundingClientRect(), b = post.getBoundingClientRect();
        if (width >= 1200) expect(a.left).to.be.at.least(b.right - 1);
        else expect(a.top).to.be.at.least(b.bottom - 1);
      }));
      cy.contains('[role="tab"]', 'Following').click();
      stacked();
      ['/profile/person2', '/user-posts/person2', '/tag/react'].forEach(route => {
        cy.visit(route);
        stacked();
      });
    });
  });

  [375, 1280].forEach(width => {
    it('shows only three suggestions and replaces a followed person at ' + width + 'px', () => {
      cy.viewport(width, 900);
      mockShell(viewer);
      cy.intercept('GET', '**/api/users/suggested*', [1, 2, 3, 4, 5].map(person));
      cy.intercept('POST', '**/api/users/1/follow', { delay: 300, body: { following: true } }).as('follow');
      cy.visit('/');
      cy.get('[data-testid="suggested-user"]').should('have.length', 3);
      cy.get('[data-username="person4"]').should('not.exist');
      cy.get('[data-username="person1"] [data-testid="suggested-follow"]').click().should('be.disabled');
      cy.wait('@follow');
      cy.get('[data-testid="suggested-user"]').should('have.length', 3);
      cy.get('[data-username="person1"]').should('not.exist');
      cy.get('[data-username="person4"]').should('be.visible');
      cy.get('[data-username="person5"]').should('not.exist');
    });
  });

  it('offers Logout only in Settings while keeping both compatibility selectors', () => {
    cy.viewport(1280, 900);
    mockShell(viewer);
    cy.visit('/');
    cy.get('nav').should('not.contain', 'Logout');
    cy.viewport(375, 900);
    cy.get('[aria-label="Open navigation menu"]').click();
    cy.get('#mobile-navigation').should('not.contain', 'Logout');
    cy.get('body').type('{esc}');
    cy.get('[data-testid="nav-settings"]').click();
    cy.get('[role="menuitem"]').filter(':contains("Logout")').should('have.length', 1);
    cy.get('[data-testid="nav-logout"]').find('[data-testid="settings-logout"]').click();
    cy.get('[role="dialog"]').should('contain', 'Logout from this device').and('contain', 'Logout from all devices');
  });
});

describe('server-sanitized inline rendering', () => {
  it('retains server sanitization and formatting through expansion', () => {
    cy.apiSignup().then(user => {
      cy.apiCreatePost({ title: 'Safe rich preview', bodyHtml: '<p onclick="window.unsafeBody = true">A <strong>formatted</strong> preview.</p>'
        + '<p>Readable software is easier to maintain.</p>'.repeat(12)
        + '<p><a href="javascript:window.unsafeBody=true">A stripped unsafe URL</a></p>' });
      cy.visit('/user-posts/' + user.username);
      cy.get(toggle).should('have.text', 'Read More').click();
      cy.get(body + ' strong').should('be.visible');
      cy.get(body + ' [onclick], ' + body + ' [href^="javascript:"]').should('not.exist');
      cy.window().should(win => expect(win.unsafeBody).to.equal(undefined));
      cy.get(toggle).click();
      cy.get(body + ' [onclick], ' + body + ' [href^="javascript:"]').should('not.exist');
    });
  });
});
