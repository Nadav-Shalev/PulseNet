import { article, mockShell, person, themeVisit, viewer } from '../support/uiFixtures';

const longWord = 'longunbrokencontent'.repeat(5);
const comment = { id: 1, user: { ...person(3), name: 'Sam Rivera' }, body_html: '<p>A helpful explanation. Here is a long link: https://example.com/' + longWord + '</p>', created_at: '2026-10-10T10:00:00+00:00', replies: [] };
const report = { id: 1, status: 'open', reason: 'spam', author: person(2), reporter: person(3), details: 'Please review this post.', created_at: '2026-10-10T10:00:00+00:00', target: { type: 'post', id: 1, post_title: 'Community report', excerpt: 'An example report for the moderation queue.' } };

function noOverflow() {
  cy.document().should(doc => expect(doc.documentElement.scrollWidth).to.be.at.most(doc.documentElement.clientWidth));
  cy.get('body').then(body => {
    body.find('[data-testid="post-card"]').each((_, card) => expect(card.scrollWidth).to.be.at.most(card.clientWidth));
  });
}

// Check actual rendered text against the composed surface, including translucent
// MUI backgrounds. Disabled controls are intentionally outside the text check.
function readableText() {
  cy.get('h1,h2,h3,p,.MuiTypography-caption,.MuiButton-contained:not(:disabled),.MuiInputLabel-root:not(.Mui-disabled)').filter(':visible').each(el => {
    const node = el[0];
    if (!node.textContent.trim()) return;
    const win = node.ownerDocument.defaultView;
    const rgba = text => (text.match(/[\d.]+/g) || []).map(Number);
    const blend = (fg, bg) => fg.slice(0, 3).map((v, i) => v * (fg[3] ?? 1) + bg[i] * (1 - (fg[3] ?? 1)));
    const surface = element => {
      if (!element) return [255, 255, 255];
      const bg = rgba(win.getComputedStyle(element).backgroundColor);
      return blend(bg, (bg[3] ?? 1) < 1 ? surface(element.parentElement) : [255, 255, 255]);
    };
    const luminance = rgb => rgb.map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
      .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
    const style = win.getComputedStyle(node);
    const bg = surface(node);
    const a = luminance(blend(rgba(style.color), bg));
    const b = luminance(bg);
    const size = parseFloat(style.fontSize);
    const minimum = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700) ? 3 : 4.5;
    expect((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), node.textContent.slice(0, 65)).to.be.at.least(minimum);
  });
}

describe('polish visual and accessibility checks', () => {
  [false, true].forEach(dark => {
    [375, 768, 1280].forEach(width => {
      it('renders key screens at ' + width + 'px in ' + (dark ? 'dark' : 'light') + ' mode', () => {
        const mode = dark ? 'dark' : 'light';
        const shot = name => {
          // Capture settled content, after requests and click ripples complete.
          cy.get('[role="progressbar"]:visible,.MuiTouchRipple-childLeaving').should('not.exist');
          noOverflow();
          readableText();
          cy.screenshot(mode + '-' + width + '-' + name, { capture: 'fullPage', overwrite: true });
        };
        cy.viewport(width, 900);
        mockShell({ ...viewer, role: 'admin' });
        cy.intercept({ method: 'GET', pathname: '/api/articles' }, [article(1, 'Building thoughtful interfaces'), article(2, longWord)]);
        cy.intercept('GET', '**/api/tags/trending*', [{ name: 'react', post_count: 4 }, { name: 'accessibility', post_count: 3 }]);
        cy.intercept('GET', '**/api/users/suggested*', [{ ...person(2), name: 'Maya Chen' }, { ...person(3), name: 'Nova', is_agent: true }]);
        cy.intercept('GET', '**/api/articles/1/comments', [comment]);
        cy.intercept('GET', '**/api/users/person2', { ...person(2), name: 'Maya Chen', bio: 'Frontend engineer. ' + longWord, followers_count: 12, following_count: 5 });
        cy.intercept('GET', '**/api/users/nova_ai', { ...person(4), username: 'nova_ai', name: 'Nova', bio: 'Curious about thoughtful software.', is_agent: true, personality: 'I explore how people build useful, accessible software. I share practical examples, ask clear questions, and enjoy discussing React, design, and the web.\n\nI explain tradeoffs in plain language and welcome different approaches.' });
        cy.intercept('GET', '**/api/admin/reports*', [report]);
        cy.intercept('GET', '**/api/admin/users*', [person(2), { ...person(3), is_banned: true }]);
        themeVisit('/', dark);
        cy.get('[data-testid="nav-profile"]').should('exist');
        cy.get('[data-testid="post-card"]').should('have.length', 2);
        cy.get('[data-testid="suggested-user"]').should('have.length', 2);
        cy.document().should(doc => expect(doc.defaultView.getComputedStyle(doc.documentElement).colorScheme).to.equal(mode));
        shot('home');
        cy.contains('[data-testid="post-card"]', 'Building thoughtful').contains('button', 'Read More').click();
        cy.get('[data-testid="comment"]').should('exist');
        noOverflow();
        readableText();
        cy.screenshot(mode + '-' + width + '-post-comments', { capture: 'viewport', overwrite: true });
        cy.get('[aria-label="Close post"]').click();

        themeVisit('/profile/person2', dark);
        cy.get('[data-testid="profile-name"]').should('contain', 'Maya');
        cy.get('[data-testid="post-card"]').should('have.length', 2);
        cy.contains('No more posts').should('exist');
        shot('profile');
        themeVisit('/profile/nova_ai', dark);
        cy.get('[data-testid="profile-persona"]').should('be.visible');
        cy.get('[data-testid="post-card"]').should('have.length', 2);
        cy.contains('No more posts').should('exist');
        shot('agent-profile');
        themeVisit('/new-post', dark);
        cy.get('.ql-editor[role="textbox"]').should('have.attr', 'aria-label', 'Post body').type('A readable draft with a clear purpose.');
        cy.get('[data-testid="post-title-input"]').type('A new idea');
        shot('editor');
        themeVisit('/edit-profile', dark);
        cy.contains('button', 'Save Changes').should('be.visible');
        shot('edit-profile');

        mockShell();
        themeVisit('/login', dark);
        cy.get('[data-testid="login-submit"]').click();
        cy.contains('Email and password are required.').should('be.visible');
        shot('login-error');
        themeVisit('/signup', dark);
        cy.get('[data-testid="signup-email"]').should('be.visible');
        shot('signup');
        cy.intercept('POST', '**/api/password/forgot', { statusCode: 503, body: { error: 'Email delivery is temporarily unavailable. Please try again later.' } });
        themeVisit('/forgot-password', dark);
        cy.get('[data-testid="forgot-email"]').type('alex@example.com');
        cy.get('[data-testid="forgot-submit"]').click();
        cy.get('[data-testid="forgot-error"]').should('be.visible');
        shot('forgot-error');
        themeVisit('/reset-password#token=visual-test-only', dark);
        cy.get('[data-testid="reset-password"]').should('be.visible');
        shot('reset');
        themeVisit('/reset-password', dark);
        cy.get('[data-testid="reset-error"]').should('be.visible');
        shot('reset-error');

        mockShell({ ...viewer, role: 'admin' });
        themeVisit('/admin', dark);
        cy.get('[data-testid="admin-report"]').should('be.visible');
        shot('admin-reports');
        cy.get('[data-testid="admin-tab-users"]').click();
        cy.get('[data-testid="admin-user-row"]').should('have.length', 2);
        shot('admin-users');

        cy.intercept({ method: 'GET', pathname: '/api/articles' }, []);
        themeVisit('/', dark);
        cy.get('[data-testid="nav-profile"]').should('exist');
        cy.contains('No posts yet.').should('be.visible');
        shot('empty');
        cy.intercept({ method: 'GET', pathname: '/api/articles' }, { statusCode: 503, body: { error: 'Posts are temporarily unavailable. Please retry.' } });
        cy.intercept('GET', '**/api/tags/trending*', { statusCode: 503, body: {} });
        cy.intercept('GET', '**/api/users/suggested*', { statusCode: 503, body: {} });
        themeVisit('/', dark);
        cy.get('[data-testid="nav-profile"]').should('exist');
        cy.contains('Posts are temporarily unavailable.').should('be.visible');
        cy.contains('Suggestions are unavailable.').should('be.visible');
        shot('error');
      });
    });
  });

});
