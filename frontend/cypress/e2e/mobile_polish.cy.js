import { article, mockShell, person, themeVisit, viewer } from '../support/uiFixtures';

const body = '[data-testid="post-body"]';
const toggle = '[data-testid="post-body-toggle"]';

// Count painted text rows, rather than assuming all rich blocks share a height.
function threeCleanLines(content) {
  const node = content[0], doc = node.ownerDocument;
  const clip = node.parentElement.getBoundingClientRect();
  const walker = doc.createTreeWalker(node, doc.defaultView.NodeFilter.SHOW_TEXT);
  const rows = [];
  let text;
  while ((text = walker.nextNode())) {
    if (!text.textContent.trim()) continue;
    const range = doc.createRange();
    range.selectNodeContents(text);
    for (const rect of range.getClientRects()) {
      if (!rect.width || rect.top >= clip.bottom - 1) continue;
      expect(rect.bottom, 'no partially clipped text row').to.be.at.most(clip.bottom + 1);
      const middle = (rect.top + rect.bottom) / 2;
      if (!rows.some(row => Math.abs(row - middle) < 4)) rows.push(middle);
    }
  }
  expect(rows, 'complete visible text lines').to.have.length(3);
  const style = doc.defaultView.getComputedStyle(node.parentElement);
  expect(style.maskImage || style.webkitMaskImage || 'none').to.equal('none');
}

describe('final mobile polish', () => {
  [375, 768].forEach(width => {
    it('puts posts before discovery in visual and DOM order at ' + width + 'px', () => {
      cy.viewport(width, 812);
      mockShell(viewer);
      cy.intercept({ method: 'GET', pathname: '/api/articles' }, [article(1), article(2)]);
      cy.intercept('GET', '**/api/users/suggested*', [1, 2, 3, 4].map(person));
      cy.intercept('GET', '**/api/tags/trending*', [{ name: 'react', post_count: 2 }]);
      cy.visit('/');
      cy.get('[data-testid="post-card"]').first().should(([post]) => {
        expect(post.getBoundingClientRect().top, 'first post is in initial viewport').to.be.lessThan(400);
      });
      cy.get('[data-testid="home-sidebar"]').should(([side]) => {
        const panel = side.ownerDocument.getElementById('feed-panel');
        expect(side.getBoundingClientRect().top).to.be.at.least(panel.getBoundingClientRect().bottom - 1);
        expect(panel.compareDocumentPosition(side) & 4, 'feed precedes discovery in DOM').to.equal(4);
      });
      cy.get('[data-testid="suggested-user"]').should('have.length', 3);
      cy.get('[data-testid="suggested-follow"]').first().should('be.enabled');
      cy.document().should(doc => expect(doc.documentElement.scrollWidth).to.be.at.most(doc.documentElement.clientWidth));
      cy.contains('[role="tab"]', 'Following').click();
      cy.get('[data-testid="post-card"]').first().should('exist');
      cy.get('[data-testid="home-sidebar"]').should(([side]) => {
        expect(side.getBoundingClientRect().top).to.be.at.least(side.ownerDocument.getElementById('feed-panel').getBoundingClientRect().bottom - 1);
      });
    });
  });

  [false, true].forEach(dark => {
    it('shows exactly three clean rich-text lines in ' + (dark ? 'dark' : 'light') + ' mode', () => {
      cy.viewport(375, 812);
      mockShell(viewer);
      const samples = [
        '<p>First <strong>bold</strong> line.</p><p>Second line.</p><p>Third line.</p><p>Fourth hidden line.</p>',
        '<p>One line.<br>Two lines.<br>Three lines.<br>Fourth hidden line.</p>',
        '<h1>A heading</h1><p>Second line.</p><p>Third line.</p><p>Fourth hidden line.</p>',
        '<ul><li>First item.</li><li>Second item.</li><li>Third item.</li><li>Fourth hidden item.</li></ul>',
        '<pre><code>First code line.\nSecond code line.\nThird code line.\nFourth hidden line.</code></pre>',
        '<p>' + 'A longer sentence that wraps cleanly onto the next line. '.repeat(6) + '</p>',
      ];
      samples.forEach((html, index) => {
        cy.intercept('GET', '**/api/articles/1', { ...article(1), body_html: html });
        themeVisit('/', dark);
        cy.get(toggle).should('have.text', 'Read More');
        cy.get(body + ' .rich-text').should(threeCleanLines);
        cy.get(toggle).click().should('be.focused').and('have.text', 'Read Less');
        cy.get(body + ' .rich-text').invoke('html').should('equal', html);
        cy.get(toggle).click().should('be.focused').and('have.text', 'Read More');
        cy.get(body + ' .rich-text').should(threeCleanLines);
        cy.location('pathname').should('equal', '/');
        cy.get('[data-testid="post-dialog"]').should('not.exist');
        if (index === 0 || index === 2) cy.screenshot('mobile-' + (dark ? 'dark' : 'light') + '-preview-' + index, { capture: 'viewport', overwrite: true });
      });
    });
  });

  it('limits mobile headings in cards and Comments while retaining desktop typography', () => {
    cy.viewport(375, 812);
    mockShell(viewer);
    const html = '<h1>Heading one</h1><h2>Heading two</h2><h3>Heading three</h3><p>Body copy.</p>';
    cy.intercept('GET', '**/api/articles/1', { ...article(1), body_html: html });
    cy.visit('/');
    cy.get(toggle).click();
    const smallHeadings = elements => [...elements].forEach(el => {
      const style = el.ownerDocument.defaultView.getComputedStyle(el);
      expect(parseFloat(style.fontSize)).to.be.at.most(23);
      expect(el.scrollWidth).to.be.at.most(el.clientWidth);
    });
    cy.get(body + ' h1,' + body + ' h2,' + body + ' h3').should(smallHeadings);
    cy.get('[data-testid="comment-button"]').click();
    cy.get('[data-testid="post-dialog"] .rich-text h1,[data-testid="post-dialog"] .rich-text h2,[data-testid="post-dialog"] .rich-text h3').should(smallHeadings);
    cy.get('[aria-label="Close post"]').click();
    cy.viewport(1280, 900);
    cy.get(body + ' h1').should(([el]) => expect(parseFloat(el.ownerDocument.defaultView.getComputedStyle(el).fontSize)).to.be.greaterThan(23));
  });

  it('decodes the bundled production brand and favicon on a nested mobile route and reload', () => {
    cy.viewport(375, 812);
    mockShell();
    cy.visit('/profile/person2');
    const checkBrand = () => {
      cy.contains('nav a', 'PulseNet').find('img').should(([img]) => {
        expect(img.complete).to.equal(true);
        expect(img.naturalWidth).to.equal(32);
        expect(img.naturalHeight).to.equal(32);
      });
      cy.get('link[rel="icon"]').invoke('attr', 'href').then(href => {
        expect(href).to.match(/pulsenet-mark[^/]*\.svg/);
        cy.contains('nav a', 'PulseNet').find('img').should('have.attr', 'src', href);
        cy.request(href).then(response => {
          expect(response.status).to.equal(200);
          expect(response.headers['content-type']).to.include('image/svg+xml');
          expect(response.body).to.include('width="32" height="32"');
        });
      });
    };
    checkBrand();
    cy.reload();
    checkBrand();
    cy.contains('nav a', 'PulseNet').click();
    cy.location('pathname').should('equal', '/');
    cy.get('[data-testid="nav-settings"]').click();
    cy.get('[role="menu"][aria-label="Settings"]').should('be.visible');
  });

  it('keeps mobile loading, empty and failed feed feedback before discovery', () => {
    cy.viewport(375, 812);
    mockShell(viewer);
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, { delay: 700, body: [] });
    cy.visit('/');
    const beforeSide = selector => cy.get(selector).should(([state]) => {
      const side = state.ownerDocument.querySelector('[data-testid="home-sidebar"]');
      expect(state.getBoundingClientRect().bottom).to.be.at.most(side.getBoundingClientRect().top);
    });
    beforeSide('#feed-panel [aria-label="Loading posts"]');
    cy.contains('No posts yet.').should('be.visible');
    beforeSide('#feed-panel');
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, { statusCode: 503, body: { error: 'Feed unavailable' } });
    cy.reload();
    cy.get('#feed-panel [role="alert"]').should('contain', 'Feed unavailable');
    beforeSide('#feed-panel [role="alert"]');
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, [article(1)]);
    cy.get('#feed-panel').contains('button', 'Retry').click();
    cy.get('[data-testid="post-card"]').should('be.visible');
  });
});
