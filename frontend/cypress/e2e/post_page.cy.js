// /post/:postId, the page AI Activity's "View post" opens: one post as the feed
// shows it (SinglePost), on the real stack, and what it says when there is none.
describe('a post on its own page', () => {
  const signupAdmin = () =>
    cy.apiSignup().then((admin) => cy.task('makeAdmin', admin.username).then(() => admin))

  it('shows the post with its likes and comments, and survives a reload', () => {
    cy.apiSignup().then((author) => {
      const title = `A post with its own page, by ${author.username}`
      cy.apiCreatePost({ title, bodyHtml: '<p>The whole body of the post.</p>' }).then((post) => {
        cy.apiComment(post.id, '<p>A first comment</p>')
        cy.apiSignup().then(() => {
          cy.visit(`/post/${post.id}`)
          cy.get('[data-testid="post-page"] h1').should('have.text', `Post by @${author.username}`)
          cy.get('[data-testid="post-card"]').should('have.length', 1).and('contain', title)
          cy.get('[data-testid="comment-count"]').should('contain', '1')

          cy.get('[data-testid="like-button"]').click()
          cy.get('[data-testid="like-count"]').should('contain', '1')

          cy.get('[data-testid="comment-button"]').click()
          cy.get('[data-testid="post-dialog"]').within(() => {
            cy.contains('The whole body of the post.')
            cy.get('[data-testid="comment"]').should('have.length', 1).and('contain', 'A first comment')
          })
          cy.get('[aria-label="Close post"]').click()

          // A deep link: the server sends the app for /post/:id, the like is kept.
          cy.reload()
          cy.get('[data-testid="post-card"]').should('contain', title)
          cy.get('[data-testid="like-count"]').should('contain', '1')
        })
      })
    })
  })

  it('an admin who deletes it is sent home', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Soon gone, by ${author.username}` }).then((post) => {
        signupAdmin().then(() => {
          cy.visit(`/post/${post.id}`)
          cy.get('[data-testid="admin-delete-post"]').click()
          cy.get('[data-testid="post-delete-confirm"]').click()
          cy.location('pathname').should('eq', '/')
          cy.visit(`/post/${post.id}`)
          cy.get('[data-testid="post-page-not-found"]').should('contain', 'does not exist')
        })
      })
    })
  })

  it('says so when there is no such post, and asks nothing for a bad id', () => {
    cy.intercept({ method: 'GET', pathname: /^\/api\/articles\/[^/]+$/ }).as('detail')
    cy.visit('/post/999999999')
    cy.wait('@detail').its('response.statusCode').should('eq', 404)
    cy.get('[data-testid="post-page-not-found"]').should('be.visible')
    cy.get('[data-testid="post-card"]').should('not.exist')

    // (The dev server's StrictMode asks twice on mount, so count from here.)
    cy.get('@detail.all').then((asked) => {
      cy.visit('/post/abc')
      cy.get('[data-testid="post-page-not-found"]').should('be.visible')
      cy.get('@detail.all').should('have.length', asked.length)   // nothing new was asked
    })
  })

  it('offers Retry when the post cannot be loaded', () => {
    let down = true
    cy.intercept({ method: 'GET', pathname: /^\/api\/articles\/\d+$/ }, (req) => {
      if (down) req.reply({ statusCode: 503, body: { error: 'Database unavailable' } })
    })
    cy.apiSignup().then(() => {
      cy.apiCreatePost({ title: 'Back after a retry' }).then((post) => {
        cy.visit(`/post/${post.id}`)
        cy.get('[data-testid="post-page-error"]').should('contain', 'Database unavailable').then(() => { down = false })
        cy.get('[data-testid="post-page-error"]').contains('button', 'Retry').click()
        cy.get('[data-testid="post-card"]').should('contain', 'Back after a retry')
      })
    })
  })
})
