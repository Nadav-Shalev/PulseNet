// Comments, against the real database (the backend tests use a fake one, so this
// is what runs the comments SQL on MySQL): the thread is read and written in the
// post's dialog, replies nest one level deep, only a comment's writer may delete
// it, every feed counts comments, and deleting a post takes its whole thread with it.
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

describe('comments', () => {
  const dialog = () => cy.get('[data-testid="post-dialog"]')
  const openComments = () => {
    cy.get('[data-testid="comment-button"]').first().click()
    return dialog().should('be.visible')
  }
  const cardCount = (n) => cy.get('[data-testid="comment-count"]').first().should('have.text', String(n))

  it('a reader comments and replies from the post dialog, and the thread survives a reload', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Comment on me, by ${author.username}` })
      cy.apiSignup().then((reader) => {
        cy.visit(`/profile/${author.username}`)
        cardCount(0)

        openComments().within(() => {
          cy.get('[data-testid="comments-empty"]').should('have.text', 'No comments yet.')
          // Typed markup stays text: the box escapes it, so the sanitizer has nothing to strip.
          cy.get('[data-testid="comment-input"]').type('Use <div> & <b>{enter}on two lines')
          cy.get('[data-testid="comment-submit"]').click()

          cy.get('[data-testid="comment"]').should('have.length', 1).first().within(() => {
            cy.contains(`@${reader.username}`)
            cy.get('[data-testid="comment-body"]').should('have.text', 'Use <div> & <b>on two lines')
              .find('br').should('have.length', 1)
            cy.get('[data-testid="reply-button"]').click()
          })
          cy.get('[data-testid="reply-input"]').type('And a reply')
          cy.get('[data-testid="reply-submit"]').click()

          cy.get('[data-testid="comment-replies"] [data-testid="comment"]').should('have.length', 1)
            .find('[data-testid="comment-body"]').should('have.text', 'And a reply')
          // A reply cannot be answered: replies are one level deep.
          cy.get('[data-testid="comment-replies"] [data-testid="reply-button"]').should('not.exist')
          cy.get('[data-testid="comment-input"]').should('have.value', '')
        })
        cardCount(2)

        // The count comes back from the feed query, and the thread from the comments query.
        cy.reload()
        cardCount(2)
        openComments().within(() => {
          cy.get('[data-testid="comment"]').should('have.length', 2)
          cy.get('[data-testid="comment-replies"]').first()
            .should('contain', 'And a reply')
            .and('not.contain', 'Use <div>')
        })
      })
    })
  })

  it('only the writer may delete a comment, and deleting it takes its replies along', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost().then((post) => {
        cy.apiComment(post.id, '<p>Top comment by the author</p>').then(({ comment }) => {
          cy.apiSignup().then(() => {
            cy.apiComment(post.id, '<p>First reply by the reader</p>', comment.id)
            cy.apiComment(post.id, '<p>Second reply by the reader</p>', comment.id)

            // The reader can delete their own replies only.
            cy.visit(`/profile/${author.username}`)
            cardCount(3)
            openComments().within(() => {
              cy.get('[data-testid="comment-delete"]').should('have.length', 2)
              cy.get('[data-testid="comment"]').first().find('[data-testid="comment-delete"]').should('not.exist')
              cy.get('[data-testid="comment-replies"] [data-testid="comment-delete"]').first().click()
            })
            cy.get('[data-testid="comment-delete-confirm"]').click()
            dialog().within(() => {
              cy.get('[data-testid="comment"]').should('have.length', 2)
              cy.contains('First reply by the reader').should('not.exist')
            })
            cardCount(2)

            // The author deletes the top comment; the reader's remaining reply goes with it.
            cy.apiLogin(author)
            cy.reload()
            openComments().within(() => {
              cy.get('[data-testid="comment-delete"]').should('have.length', 1).click()
            })
            cy.contains('Its replies will be deleted too.')
            cy.get('[data-testid="comment-delete-confirm"]').click()
            dialog().within(() => {
              cy.get('[data-testid="comments-empty"]').should('be.visible')
              cy.get('[data-testid="comment"]').should('not.exist')
            })
            cardCount(0)
            cy.request(api(`/articles/${post.id}/comments`)).its('body').should('deep.equal', [])
          })
        })
      })
    })
  })

  it('a logged-out visitor reads the thread on a phone, and is sent to log in to write', () => {
    cy.viewport('iphone-x')
    cy.apiSignup().then((author) => {
      cy.apiCreatePost().then((post) => {
        cy.apiComment(post.id, '<p>Visible to everyone</p>')
        cy.clearCookies()

        cy.visit(`/profile/${author.username}`)
        cardCount(1)
        openComments().within(() => {
          cy.get('[data-testid="comment-body"]').should('have.text', 'Visible to everyone')
          cy.get('[data-testid="comments-section"]').then(($section) => {
            expect($section[0].scrollWidth, 'no sideways scroll').to.be.at.most($section[0].clientWidth)
          })
          cy.get('[data-testid="comment-input"]').should('not.exist')
          cy.get('[data-testid="reply-button"]').should('not.exist')
          cy.get('[data-testid="comment-delete"]').should('not.exist')
          cy.get('[data-testid="comment-login"]').click()
        })
        cy.location('pathname').should('eq', '/login')
      })
    })
  })

  it('every feed counts comments; the API sanitizes, nests one level, and checks who writes', () => {
    const tag = `commenttag${Date.now()}`
    const send = (method, route, body) =>
      cy.request({ method, url: api(route), body, failOnStatusCode: false })
    const expectStatus = (method, route, body, status) =>
      send(method, route, body).its('status').should('equal', status)
    const findPost = (body, id) => (Array.isArray(body) ? body.find((p) => p.id === id) : body)

    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ tags: [tag] }).then((post) => {
        cy.apiComment(post.id, '<p>first</p>').then(({ comment: top }) => {
          cy.apiSignup() // the reader
          cy.apiFollow(author.id)
          cy.apiComment(post.id, '<p>a reply</p>', top.id).then(({ comment: reply, comment_count }) => {
            expect(comment_count).to.equal(2)
            expect(reply.parent_id).to.equal(top.id)

            // One counts query serves every feed, likes and comments together.
            ;[
              '/articles',
              `/articles?username=${author.username}`,
              `/articles?tag=${tag}`,
              '/articles?feed=following',
              `/articles/${post.id}`,
            ].forEach((route) =>
              cy.request(api(route)).its('body').then((body) => {
                const found = findPost(body, post.id)
                expect(found, `${route} has the post`).to.exist
                expect(found.comment_count, `${route} comment_count`).to.equal(2)
              }),
            )

            // The tree, with no email anywhere.
            cy.request(api(`/articles/${post.id}/comments`)).its('body').then((tree) => {
              expect(tree.map((c) => c.id)).to.deep.equal([top.id])
              expect(tree[0].replies.map((r) => r.id)).to.deep.equal([reply.id])
              expect(JSON.stringify(tree)).not.to.contain('@example.com')
            })

            // Replies are one level deep, and the parent must be on the same post.
            expectStatus('POST', `/articles/${post.id}/comments`, { body_html: '<p>deeper</p>', parent_id: reply.id }, 400)
            cy.apiCreatePost().then((other) => {
              expectStatus('POST', `/articles/${other.id}/comments`, { body_html: '<p>x</p>', parent_id: top.id }, 400)
              // The limit is on visible text: 2000 characters pass, 2001 do not.
              expectStatus('POST', `/articles/${other.id}/comments`, { body_html: 'a'.repeat(2000) }, 201)
              expectStatus('POST', `/articles/${other.id}/comments`, { body_html: 'a'.repeat(2001) }, 400)
            })
            expectStatus('POST', `/articles/${post.id}/comments`, { body_html: '<p> </p>' }, 400)
            expectStatus('POST', '/articles/999999999/comments', { body_html: '<p>x</p>' }, 404)
            expectStatus('GET', '/articles/999999999/comments', undefined, 404)

            // Sanitized on the way in (what is stored) and on the way out.
            const dirty = '<p>safe</p><script>alert(1)</script><img src=x onerror="alert(2)">' +
              '<a href="javascript:alert(3)">link</a>'
            cy.apiComment(post.id, dirty).then(({ comment }) => {
              expect(comment.body_html).to.contain('<p>safe</p>')
              expect(comment.body_html).not.to.match(/<script|onerror|javascript:/i)
              cy.request(api(`/articles/${post.id}/comments`)).its('body').then((tree) => {
                const stored = tree.find((c) => c.id === comment.id)
                expect(stored.body_html).not.to.match(/<script|onerror|javascript:/i)
              })
            })

            // Only the writer may delete: the reader cannot delete the author's comment.
            expectStatus('DELETE', `/comments/${top.id}`, undefined, 403)
            expectStatus('DELETE', '/comments/999999999', undefined, 404)

            // Logged out, the thread is public but writing is not.
            cy.clearCookies()
            expectStatus('POST', `/articles/${post.id}/comments`, { body_html: '<p>x</p>' }, 401)
            expectStatus('DELETE', `/comments/${reply.id}`, undefined, 401)
            expectStatus('GET', `/articles/${post.id}/comments`, undefined, 200)

            // The author can still delete the post: ON DELETE CASCADE removes its
            // comments and their replies (comments.parent_id points at comments).
            cy.apiLogin(author)
            cy.request('DELETE', api(`/articles/${post.id}`))
              .its('body').should('deep.equal', { deleted: true, id: post.id })
            expectStatus('GET', `/articles/${post.id}/comments`, undefined, 404)
          })
        })
      })
    })
  })
})
