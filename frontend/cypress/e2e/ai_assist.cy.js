// AI assistance against the real stack: the post editor fixes grammar and drafts a
// body from the title, the comment box proposes a comment and fixes grammar, and
// every result waits as a suggestion until it is applied. The E2E backend runs the
// fake LLM, which answers "(fake reply) " and the start of the prompt, so a test
// can tell that the right context reached it. The per-user daily limit runs its
// llm_usage writes and counts on MySQL (AI_USER_DAILY_LIMIT=5 in scripts/e2e.mjs).
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

describe('AI assistance', () => {
  const send = (route, body) => cy.request({ method: 'POST', url: api(route), body, failOnStatusCode: false })
  // Text typed into the rich editor can carry non-breaking spaces (the browser's
  // choice), so editor text is compared with every run of whitespace as one space.
  const textOf = (selector) => cy.get(selector).invoke('text').then((text) => text.replace(/\s+/g, ' ').trim())

  it('the post editor drafts a body from the title and fixes grammar, as suggestions to apply', () => {
    cy.apiSignup().then((user) => {
      cy.visit('/new-post')
      cy.get('[data-testid="ai-suggest-post"]').should('be.disabled')
      cy.get('[data-testid="ai-correct-post"]').should('be.disabled')

      cy.get('[data-testid="post-title-input"]').type('Testing React hooks')
      cy.get('[data-testid="ai-suggest-post"]').click()
      cy.get('[data-testid="ai-suggestion-body"]').should('contain', '(fake reply)').and('contain', 'Testing React hooks')
      cy.get('.ql-editor').should('not.contain', '(fake reply)') // nothing is written in before Apply
      cy.get('[data-testid="ai-apply"]').click()
      cy.get('[data-testid="ai-suggestion"]').should('not.exist')
      cy.get('.ql-editor').should('contain', 'Testing React hooks')

      cy.get('.ql-editor').clear().type('teh hooks are grate')
      cy.get('[data-testid="ai-correct-post"]').click()
      textOf('[data-testid="ai-suggestion-body"]').should('contain', 'teh hooks are grate')
      cy.get('[data-testid="ai-dismiss"]').click()
      cy.get('[data-testid="ai-suggestion"]').should('not.exist')
      textOf('.ql-editor').should('equal', 'teh hooks are grate')
      cy.get('[data-testid="ai-correct-post"]').click()
      cy.get('[data-testid="ai-apply"]').click()
      cy.get('.ql-editor').should('contain', '(fake reply)')

      cy.get('[data-testid="post-publish"]').click()
      cy.contains('Post published successfully')
      cy.request(api(`/articles?username=${user.username}`)).its('body').should('have.length', 1)
    })
  })

  it('the comment box proposes a comment from the post and fixes grammar, on a phone', () => {
    cy.viewport('iphone-x')
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: 'Hooks in depth', bodyHtml: '<p>useEffect runs after render.</p>' })
      cy.apiSignup() // the reader
      cy.visit(`/profile/${author.username}`)
      cy.get('[data-testid="comment-button"]').first().click()

      cy.get('[data-testid="post-dialog"]').within(() => {
        // The backend reads the post itself: its title reaches the model.
        cy.get('[data-testid="comment-ai-suggest"]').click()
        cy.get('[data-testid="ai-suggestion-body"]').should('contain', '(fake reply)').and('contain', 'Hooks in depth')
        cy.get('[data-testid="comment-input"]').should('have.value', '')
        // The AI buttons and the suggestion fit the phone: no sideways scroll.
        cy.get('[data-testid="comments-section"]').then(($section) => {
          expect($section[0].scrollWidth, 'no sideways scroll').to.be.at.most($section[0].clientWidth)
        })
        cy.get('[data-testid="ai-apply"]').click()
        cy.get('[data-testid="comment-input"]').invoke('val').should('contain', 'Hooks in depth')

        cy.get('[data-testid="comment-input"]').clear().type('teh docs are grate')
        cy.get('[data-testid="comment-ai-correct"]').click()
        cy.get('[data-testid="ai-suggestion-body"]').should('contain', 'teh docs are grate')
        cy.get('[data-testid="ai-apply"]').click()
        cy.get('[data-testid="comment-input"]').invoke('val').should('contain', '(fake reply)')

        cy.get('[data-testid="comment-submit"]').click()
        cy.get('[data-testid="comment"]').should('have.length', 1)
          .find('[data-testid="comment-body"]').should('contain', 'teh docs are grate')
      })
    })
  })

  it('the API needs a session, checks its input, and limits each user per day', () => {
    // Logged out: every route is a 401.
    ;['/ai/correct', '/ai/suggest-post', '/ai/suggest-comment'].forEach((route) =>
      send(route, { text: 'x', title: 'x', post_id: 1 }).its('status').should('equal', 401),
    )

    cy.apiSignup().then(() => {
      cy.apiCreatePost().then((post) => {
        cy.apiComment(post.id, '<p>A first comment</p>').then(({ comment }) => {
          // Bad input is refused before the LLM, and does not count.
          send('/ai/correct', { text: 'x', format: 'markdown' }).its('status').should('equal', 400)
          send('/ai/suggest-post', { title: '' }).its('status').should('equal', 400)
          send('/ai/suggest-comment', { post_id: 999999999 }).its('status').should('equal', 404)

          // Five AI requests a day in the E2E run: these five pass...
          send('/ai/correct', { text: '<p>teh</p>', format: 'html' }).its('status').should('equal', 200)
          send('/ai/correct', { text: 'teh' }).its('status').should('equal', 200)
          send('/ai/suggest-post', { title: 'Hi', tags: ['react'] }).then((res) => {
            expect(res.status).to.equal(200)
            expect(res.body.body_html).to.contain('(fake reply)')
          })
          send('/ai/suggest-comment', { post_id: post.id }).its('status').should('equal', 200)
          send('/ai/suggest-comment', { post_id: post.id, parent_id: comment.id }).its('status').should('equal', 200)

          // ...the sixth is refused.
          send('/ai/correct', { text: 'teh' }).then((res) => {
            expect(res.status).to.equal(429)
            expect(res.body.error).to.equal("You have used today's 5 AI requests. They renew at midnight UTC.")
          })

          // Moderating this user's posts and comments never counted against it,
          // and the limit is on AI help only: commenting still works.
          cy.apiComment(post.id, '<p>Still allowed to comment</p>')
        })
      })
    })
  })
})
