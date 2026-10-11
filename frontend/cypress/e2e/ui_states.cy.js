import { article, list, mockShell, person, viewer } from '../support/uiFixtures';

describe('frontend request recovery', () => {
  beforeEach(() => { cy.viewport(1280, 800); mockShell(); });

  it('distinguishes a failed first feed page from empty data and retries', () => {
    let calls = 0;
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, req => {
      req.reply(++calls === 1 ? { statusCode: 503, body: { error: 'Feed unavailable' } } : { body: [] });
    });
    cy.visit('/');
    cy.contains('Feed unavailable').should('be.visible');
    cy.contains('No posts yet.').should('not.exist');
    cy.contains('button', 'Retry').click();
    cy.contains('No posts yet.').should('be.visible');
    cy.contains('Feed unavailable').should('not.exist');
  });

  it('keeps page one after a pagination error and retries page two without duplicates', () => {
    let secondCalls = 0;
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, req => {
      if (req.query.page === '1') req.reply(list());
      else req.reply(++secondCalls === 1 ? { statusCode: 503, body: { error: 'Next page unavailable' } } : { body: [article(11)] });
    });
    cy.visit('/user-posts/person2');
    cy.get('[data-testid="post-card"]').should('have.length', 10);
    cy.scrollTo('bottom');
    cy.contains('Next page unavailable').should('be.visible');
    cy.get('[data-testid="post-card"]').should('have.length', 10);
    cy.contains('No more posts').should('not.exist');
    cy.contains('button', 'Retry').click();
    cy.get('[data-testid="post-card"]').should('have.length', 11);
    cy.contains('No more posts').should('be.visible');
    cy.then(() => expect(secondCalls).to.equal(2));
  });

  it('starts a changed feed at page one and ignores an older pending page', () => {
    mockShell(viewer);
    let oldStarted = false;
    cy.intercept({ method: 'GET', pathname: '/api/articles' }, req => {
      if (req.query.feed !== 'following') return req.reply([article(90, 'Global result')]);
      if (req.query.page === '1') return req.reply(list());
      oldStarted = true;
      req.alias = 'oldPage';
      req.reply({ delay: 800, body: [article(88, 'Stale following result')] });
    });
    cy.visit('/');
    cy.contains('[role="tab"]', 'Following').click();
    cy.get('[data-testid="post-card"]').should('have.length', 10);
    cy.scrollTo('bottom');
    cy.wrap(null).should(() => expect(oldStarted).to.equal(true));
    cy.contains('[role="tab"]', 'Global').click();
    cy.contains('Global result').should('be.visible');
    cy.wait('@oldPage');
    cy.get('[data-testid="post-card"]').should('have.length', 1);
    cy.contains('Stale following result').should('not.exist');
  });

  it('recovers a failed post detail load instead of leaving the spinner active', () => {
    let calls = 0;
    cy.intercept('GET', '**/api/articles/1', req => req.reply(++calls === 1
      ? { statusCode: 503, body: { error: 'Post unavailable' } } : { body: article(1) }));
    cy.visit('/');
    cy.get('[data-testid="comment-button"]').first().click();
    cy.get('[data-testid="post-dialog"]').within(() => {
      cy.contains('Post unavailable').should('be.visible');
      cy.get('[aria-label="Loading post"]').should('not.exist');
      cy.contains('button', 'Retry').click();
    });
    cy.get('[data-testid="post-dialog"]').should('contain', 'A better developer experience');
    cy.then(() => expect(calls).to.equal(2));
  });

  it('shows user-search failures, retains the query, and retries an empty result', () => {
    let fail = true;
    cy.intercept({ method: 'GET', pathname: '/api/users' }, req => req.reply(fail
      ? { statusCode: 503, body: { error: 'Search unavailable' } } : { body: [] }));
    cy.visit('/users');
    cy.get('input').type('alex');
    cy.contains('Search unavailable').should('be.visible');
    cy.contains('No users found.').should('not.exist');
    cy.then(() => { fail = false; });
    cy.contains('button', 'Retry').click();
    cy.contains('No users found. Try another name.').should('be.visible');
    cy.get('input').should('have.value', 'alex');
  });

  it('ignores an old search pagination response after the query changes', () => {
    cy.viewport(375, 500);
    let started = false;
    cy.intercept({ method: 'GET', pathname: '/api/users' }, req => {
      if (req.query.q === 'fresh') return req.reply([{ ...person(55), name: 'Fresh result' }]);
      if (req.query.offset === '0') return req.reply(Array.from({ length: 10 }, (_, i) => person(i + 1)));
      started = true;
      req.alias = 'oldUsers';
      req.reply({ delay: 900, body: [{ ...person(99), name: 'Stale user' }] });
    });
    cy.visit('/users');
    cy.get('tbody tr').should('have.length', 10);
    cy.scrollTo('bottom');
    cy.wrap(null).should(() => expect(started).to.equal(true));
    cy.get('input').type('fresh');
    cy.contains('Fresh result').should('be.visible');
    cy.wait('@oldUsers');
    cy.get('tbody tr').should('have.length', 1);
    cy.contains('Stale user').should('not.exist');
  });

  it('keeps current tag suggestions when an older query finishes later', () => {
    mockShell(viewer);
    let started = false;
    cy.intercept('GET', '**/api/tags/search*', req => {
      if (req.query.q === 'rea') {
        started = true; req.alias = 'oldTags';
        req.reply({ delay: 900, body: [{ name: 'old-tag' }] });
      } else { req.alias = 'newTags'; req.reply([{ name: 'react' }]); }
    });
    cy.visit('/new-post');
    cy.get('.MuiAutocomplete-root input').type('rea');
    cy.wrap(null).should(() => expect(started).to.equal(true));
    cy.get('.MuiAutocomplete-root input').type('ct');
    cy.wait('@newTags');
    cy.wait('@oldTags');
    cy.get('[role="option"]').should('contain', 'react').and('not.contain', 'old-tag');
  });

  it('lets the feed and suggestions work when trending fails, then retries trending', () => {
    cy.intercept('GET', '**/api/users/suggested*', [person(2)]);
    let fail = true;
    cy.intercept('GET', '**/api/tags/trending*', req => req.reply(fail
      ? { statusCode: 503, body: { error: 'Unavailable' } } : { body: [] }));
    cy.visit('/');
    cy.get('[data-testid="post-card"]').should('be.visible');
    cy.get('[data-testid="who-to-follow"]').should('contain', 'Person 2');
    cy.get('[data-testid="trending-tags"]').should('contain', 'Trending tags are unavailable.');
    cy.then(() => { fail = false; });
    cy.get('[data-testid="trending-tags"]').contains('button', 'Retry').click();
    cy.get('[data-testid="trending-empty"]').should('be.visible');
  });

  it('keeps each suggested follow disabled until its own request finishes', () => {
    mockShell(viewer);
    cy.intercept('GET', '**/api/users/suggested*', [person(2), person(3)]);
    cy.intercept('POST', '**/api/users/2/follow', { delay: 350, body: { following: true } }).as('first');
    cy.intercept('POST', '**/api/users/3/follow', { delay: 1400, body: { following: true } }).as('second');
    cy.visit('/');
    cy.get('[data-username="person2"] button').click();
    cy.get('[data-username="person3"] button').click().should('be.disabled');
    cy.wait('@first');
    cy.get('[data-username="person2"]').should('not.exist');
    cy.get('[data-username="person3"] button').should('be.disabled');
    cy.wait('@second');
    cy.get('[data-testid="who-to-follow"]').should('contain', "You're all caught up.");
    cy.get('@second.all').should('have.length', 1);
  });

  it('keeps a profile visible after a failed follow and allows another attempt', () => {
    mockShell(viewer);
    cy.intercept('GET', '**/api/users/person2', { ...person(2), followers_count: 12, following_count: 4 });
    let fail = true;
    cy.intercept('POST', '**/api/users/2/follow', req => req.reply(fail
      ? { statusCode: 503, body: { error: 'Follow unavailable' } } : { body: { following: true } }));
    cy.visit('/profile/person2');
    cy.contains('button', /^Follow$/).click();
    cy.contains('Follow unavailable').should('be.visible');
    cy.get('[data-testid="profile-name"]').should('contain', 'Person 2');
    cy.get('[data-testid="followers-count"]').should('contain', '12');
    cy.then(() => { fail = false; });
    cy.contains('button', /^Follow$/).click();
    cy.contains('button', 'Unfollow').should('be.visible');
    cy.get('[data-testid="followers-count"]').should('contain', '13');
  });

  it('submits login with Enter once and preserves inputs on failure', () => {
    cy.intercept('POST', '**/api/login', { delay: 600, statusCode: 503, body: { error: 'Login unavailable' } }).as('login');
    cy.visit('/login');
    cy.get('[data-testid="login-email"]').type('alex@example.com');
    cy.get('[data-testid="login-password"]').type('draft-password{enter}');
    cy.get('[data-testid="login-submit"]').should('be.disabled');
    cy.get('form').trigger('submit');
    cy.wait('@login');
    cy.contains('Login unavailable').should('be.visible');
    cy.get('[data-testid="login-email"]').should('have.value', 'alex@example.com');
    cy.get('[data-testid="login-password"]').should('have.value', 'draft-password');
    cy.get('@login.all').should('have.length', 1);
  });

  it('submits signup with Enter once and preserves inputs on rejection', () => {
    cy.intercept('POST', '**/api/users', { delay: 600, statusCode: 409, body: { error: 'Account already exists' } }).as('signup');
    cy.visit('/signup');
    cy.get('[data-testid="signup-email"]').type('alex@example.com');
    cy.get('[data-testid="signup-password"]').type('draft-password');
    cy.get('[data-testid="signup-repeat-password"]').type('draft-password{enter}');
    cy.get('[data-testid="signup-submit"]').should('be.disabled');
    cy.get('form').trigger('submit');
    cy.wait('@signup');
    cy.contains('Account already exists').should('be.visible');
    cy.get('[data-testid="signup-repeat-password"]').should('have.value', 'draft-password');
    cy.get('[data-testid="signup-email"]').should('have.value', 'alex@example.com');
    cy.get('@signup.all').should('have.length', 1);
  });

  it('blocks publishing and profile saving during an upload and retains input after failure', () => {
    mockShell(viewer);
    cy.intercept('POST', '**/api/upload', { delay: 800, statusCode: 503, body: { error: 'Upload unavailable' } }).as('upload');
    const cases = [
      ['/new-post', '[data-testid="post-title-input"]', 'Publish'],
      ['/edit-profile', 'input', 'Save Changes'],
    ];
    cases.forEach(([path, input, submit]) => {
      cy.visit(path);
      const field = path === '/new-post' ? cy.get(input) : cy.contains('label', /^Name$/).invoke('attr', 'for').then(id => cy.get('#' + id));
      field.clear().type('Keep this draft');
      cy.get('input[type="file"]').selectFile({ contents: Cypress.Buffer.from('test image'), fileName: 'test.png', mimeType: 'image/png' }, { force: true });
      cy.contains('button', submit).should('be.disabled');
      cy.wait('@upload');
      cy.contains('Upload unavailable').should('be.visible');
      cy.contains('button', submit).should('not.be.disabled');
      cy.get('input').filter((_, el) => el.value === 'Keep this draft').should('have.length', 1);
    });
  });

  it('ignores reports from an older status filter', () => {
    mockShell({ ...viewer, role: 'admin' });
    let started = false;
    cy.intercept('GET', '**/api/admin/reports*', req => {
      if (req.query.status === 'open') {
        started = true; req.alias = 'oldReports';
        req.reply({ delay: 1000, body: [{ id: 1, status: 'open', reason: 'spam', author: person(2), reporter: person(3), target: { type: 'post', id: 1, post_title: 'Old open report', excerpt: 'Old' } }] });
      } else req.reply([]);
    });
    cy.visit('/admin');
    cy.wrap(null).should(() => expect(started).to.equal(true));
    cy.get('[data-testid="reports-resolved"]').click();
    cy.contains('No dismissed reports.').should('be.visible');
    cy.wait('@oldReports');
    cy.contains('Old open report').should('not.exist');
    cy.contains('No dismissed reports.').should('be.visible');
  });

  it('shows admin search loading, ignores old results, and retries failures', () => {
    mockShell({ ...viewer, role: 'admin' });
    cy.intercept('GET', '**/api/admin/reports*', []);
    let started = false;
    let fail = true;
    cy.intercept('GET', '**/api/admin/users*', req => {
      if (req.query.q === 'a') {
        started = true; req.alias = 'oldAdminUsers';
        req.reply({ delay: 1000, body: [{ ...person(8), name: 'Old admin result' }] });
      } else if (req.query.q === 'error' && fail) {
        req.reply({ statusCode: 503, body: { error: 'Admin search unavailable' } });
      } else req.reply({ delay: 250, body: [{ ...person(9), name: 'Current admin result' }] });
    });
    cy.visit('/admin');
    cy.get('[data-testid="admin-tab-users"]').click();
    cy.contains('Loading users...').should('be.visible');
    cy.contains('No users found.').should('not.exist');
    cy.get('[data-testid="admin-user-search"]').type('a');
    cy.wrap(null).should(() => expect(started).to.equal(true));
    cy.get('[data-testid="admin-user-search"]').type('b');
    cy.contains('Current admin result').should('be.visible');
    cy.wait('@oldAdminUsers');
    cy.contains('Old admin result').should('not.exist');
    cy.get('[data-testid="admin-user-search"]').clear().type('error');
    cy.contains('Admin search unavailable').should('be.visible');
    cy.contains('No users found.').should('not.exist');
    cy.then(() => { fail = false; });
    cy.contains('button', 'Retry').click();
    cy.contains('Current admin result').should('be.visible');
    cy.contains('Admin search unavailable').should('not.exist');
  });

  it('retries unavailable suggestions without hiding trending or the feed', () => {
    let fail = true;
    cy.intercept('GET', '**/api/users/suggested*', req => req.reply(fail ? { statusCode: 503, body: {} } : { body: [person(2)] }));
    cy.visit('/');
    cy.get('[data-testid="who-to-follow"]').should('contain', 'Suggestions are unavailable.');
    cy.get('[data-testid="trending-empty"]').should('exist');
    cy.get('[data-testid="post-card"]').should('exist');
    cy.then(() => { fail = false; });
    cy.get('[data-testid="who-to-follow"]').contains('button', 'Retry').click();
    cy.get('[data-testid="suggested-user"]').should('contain', 'Person 2');
  });

  it('allows manual tags when suggestions fail without clearing the draft', () => {
    mockShell(viewer);
    cy.intercept('GET', '**/api/tags/search*', { statusCode: 503, body: {} });
    cy.visit('/new-post');
    cy.get('[data-testid="post-title-input"]').type('Keep the title');
    cy.get('.ql-editor').type('Keep the body');
    cy.get('.MuiAutocomplete-root input').type('react');
    cy.contains('Tag suggestions are unavailable.').should('be.visible');
    cy.get('.MuiAutocomplete-root input').type('{enter}');
    cy.get('.MuiAutocomplete-root .MuiChip-root').should('contain', 'react');
    cy.get('[data-testid="post-title-input"]').should('have.value', 'Keep the title');
    cy.get('.ql-editor').should('contain', 'Keep the body');
  });

});
