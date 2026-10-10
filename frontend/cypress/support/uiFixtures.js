// Deterministic UI data. Network contracts match the existing API; no real writes.
export const viewer = { id: 101, name: 'Alex Morgan', username: 'alex', role: 'user', bio: 'Building things for the web.', followers_count: 12, following_count: 7, post_count: 2 };
export const person = (id) => ({ id, username: 'person' + id, name: 'Person ' + id, post_count: 3, reason: { kind: 'popular', count: 12 } });
export const article = (id, title = 'Post ' + id) => ({
  id, title, description: 'A practical conversation about building thoughtful software.',
  body_html: '<h2>A better developer experience</h2><p>Readable content with <strong>clear emphasis</strong> and useful ideas.</p><pre><code>const readable = true;</code></pre>',
  user: person(2), tag_list: ['react', 'design'], like_count: 4, comment_count: 0, created_at: '2026-10-10T10:00:00+00:00',
});
export const list = (count = 10, start = 1) => Array.from({ length: count }, (_, i) => article(start + i));
export function mockShell(me = null) {
  cy.intercept('GET', '**/api/me', me ? { body: me } : { statusCode: 401, body: { error: 'Login required' } });
  cy.intercept('GET', '**/api/tags/trending*', []);
  cy.intercept('GET', '**/api/users/suggested*', []);
  cy.intercept({ method: 'GET', pathname: '/api/articles' }, [article(1)]);
  cy.intercept('GET', '**/api/articles/1', article(1));
  cy.intercept('GET', '**/api/articles/1/comments', []);
}
export function themeVisit(path, dark) {
  cy.visit(path, { onBeforeLoad(win) {
    const original = win.matchMedia.bind(win);
    win.matchMedia = (query) => query === '(prefers-color-scheme: dark)'
      ? { matches: dark, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return true; } }
      : original(query);
  } });
}
