// Moderation against the real stack: a post or comment is checked before it is
// stored, and a blocked one comes back as a 422 that the UI shows. The E2E backend
// runs the fake LLM, whose echo is not a verdict, so here the word list decides:
// this drives the moderation path, its llm_usage rows on MySQL and the 422 in the
// browser. The LLM's own verdicts are covered by the backend tests.
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

describe('moderation', () => {
  it('a toxic comment is not published, and the rephrased one is', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Moderated post by ${author.username}` }).then((post) => {
        cy.apiSignup() // the reader
        cy.visit(`/profile/${author.username}`)
        cy.get('[data-testid="comment-button"]').first().click()

        cy.get('[data-testid="post-dialog"]').within(() => {
          cy.get('[data-testid="comment-input"]').type('Read the docs, you idiot.')
          cy.get('[data-testid="comment-submit"]').click()
          cy.get('[data-testid="comment-error"]')
            .should('have.text', 'This comment looks insulting or harassing, so it was not published. Please rephrase it.')
          cy.get('[data-testid="comment"]').should('not.exist')

          // The text stays in the box, to be rephrased.
          cy.get('[data-testid="comment-input"]').should('have.value', 'Read the docs, you idiot.')
            .clear().type('Read the docs, they cover this.')
          cy.get('[data-testid="comment-submit"]').click()
          cy.get('[data-testid="comment"]').should('have.length', 1)
          cy.get('[data-testid="comment-error"]').should('not.exist')
        })
        cy.request(api(`/articles/${post.id}/comments`)).its('body')
          .then((tree) => expect(tree.map((c) => c.body_html)).to.deep.equal(['Read the docs, they cover this.']))
      })
    })
  })

  it('a toxic post is not published from the editor', () => {
    cy.apiSignup().then((user) => {
      cy.visit('/new-post')
      cy.get('[data-testid="post-title-input"]').type('Code review notes')
      cy.get('.ql-editor').type('Whoever wrote this module: kill yourself')
      cy.get('[data-testid="post-publish"]').click()

      cy.get('[data-testid="post-error"]')
        .should('contain', 'This post looks threatening, so it was not published. Please rephrase it.')
      cy.location('pathname').should('eq', '/new-post')
      cy.request(api(`/articles?username=${user.username}`)).its('body').should('have.length', 0)
    })
  })

  it('the API answers 422 with the category, whatever the casing or spacing', () => {
    const send = (route, body) => cy.request({ method: 'POST', url: api(route), body, failOnStatusCode: false })

    cy.apiSignup().then(() => {
      cy.apiCreatePost().then((post) => {
        send(`/articles/${post.id}/comments`, { body_html: '<p>FUCK   <b>YOU</b></p>' }).then((res) => {
          expect(res.status).to.equal(422)
          expect(res.body.category).to.equal('harassment')
        })
        // A post is one check of its title, tags and body: a tag alone can block it.
        send('/articles', { article: { title: 'Fine title', body_html: '<p>Fine body</p>', tags: ['you idiot'] } })
          .its('status').should('equal', 422)
        // Developer talk is not a threat.
        send(`/articles/${post.id}/comments`, { body_html: '<p>Kill the process and restart it</p>' })
          .its('status').should('equal', 201)
        cy.request(api(`/articles/${post.id}/comments`)).its('body').should('have.length', 1)
      })
    })
  })
})
