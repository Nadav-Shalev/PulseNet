// Reports and the admin page, against the real database (the backend tests use a
// fake one, so this is what runs the reports SQL on MySQL): readers report posts and
// comments, an admin dismisses reports, deletes reported content (its reports go with
// it) and bans an author (logged out everywhere, no login, the report stays open).
// Admins are made with manage.py make-admin, through the makeAdmin task.
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

describe('reports and admin', () => {
  const dialog = () => cy.get('[data-testid="post-dialog"]')
  const reportCard = (text) => cy.contains('[data-testid="admin-report"]', text)

  // A fresh admin, logged in. Yields the user.
  const signupAdmin = () =>
    cy.apiSignup().then((admin) => cy.task('makeAdmin', admin.username).then(() => admin))

  const report = (reason, details) => {
    cy.get('[data-testid="report-dialog"]').should('be.visible').within(() => {
      cy.get('[data-testid="report-submit"]').should('be.disabled')     // a reason is required
      cy.get(`[data-testid="report-reason-${reason}"]`).click()
      if (details) cy.get('[data-testid="report-details"]').type(details)
      cy.get('[data-testid="report-submit"]').click()
    })
    return cy.get('[data-testid="report-done"]')
  }

  it('a reader reports a post and a comment, and an admin sees and dismisses them', () => {
    cy.apiSignup().then((author) => {
      const title = `Reported post by ${author.username}`
      cy.apiCreatePost({ title }).then((post) => {
        cy.apiComment(post.id, '<p>A comment that gets reported</p>')

        // The author has nothing to report on their own post.
        cy.visit(`/profile/${author.username}`)
        cy.get('[data-testid="post-card"]').should('have.length', 1)
        cy.get('[data-testid="report-post"]').should('not.exist')

        cy.apiSignup().then((reader) => {
          cy.visit(`/profile/${author.username}`)
          cy.get('[data-testid="report-post"]').click()
          report('spam', 'Looks like an ad').should('contain', 'Thanks')
          cy.get('[data-testid="report-close"]').click()
          // A second report of the same post is a no-op, and says so.
          cy.get('[data-testid="report-post"]').click()
          report('other').should('contain', 'already reported')
          cy.get('[data-testid="report-close"]').click()

          cy.get('[data-testid="comment-button"]').click()
          dialog().within(() => {
            cy.get('[data-testid="comment"]').should('have.length', 1)
            cy.get('[data-testid="comment-delete"]').should('not.exist')   // not the reader's
            cy.get('[data-testid="comment-report"]').click()
          })
          report('harassment').should('contain', 'Thanks')
          cy.get('[data-testid="report-close"]').click()

          signupAdmin().then((admin) => {
            cy.visit('/')
            cy.get('[data-testid="nav-admin"]').click()
            cy.location('pathname').should('eq', '/admin')

            // The comment's card names the post too: the note tells the post's apart.
            reportCard('Looks like an ad').within(() => {
              cy.contains(title)
              cy.contains('Spam')
              cy.contains(`@${author.username}`)
              cy.contains(`reported by @${reader.username}`)
              cy.get('[data-testid="admin-report-details"]').should('have.text', 'Note: Looks like an ad')
            })
            reportCard('A comment that gets reported').within(() => {
              cy.contains('Harassment')
              cy.contains(`Comment on “${title}”`)
              cy.get('[data-testid="report-dismiss"]').click()
            })
            cy.contains('[data-testid="admin-report"]', 'A comment that gets reported').should('not.exist')
            reportCard('Looks like an ad').should('exist')   // the post's report is still open

            cy.get('[data-testid="reports-resolved"]').click()
            reportCard('A comment that gets reported')
              .should('contain', `Dismissed by @${admin.username}`)
              .find('[data-testid="report-dismiss"]').should('not.exist')
          })
        })
      })
    })
  })

  it('an admin deletes reported content, and its reports go with it', () => {
    cy.apiSignup().then((author) => {
      const title = `To be deleted, by ${author.username}`
      cy.apiCreatePost({ title }).then((post) => {
        cy.apiComment(post.id, '<p>Delete this comment</p>').then(({ comment }) => {
          cy.apiSignup().then(() => {
            cy.apiReport({ postId: post.id }, 'misinformation')
            cy.apiReport({ commentId: comment.id }, 'hate')
          })
          signupAdmin().then(() => {
            cy.visit('/admin')
            reportCard('Delete this comment').find('[data-testid="report-delete"]').click()
            cy.get('[data-testid="admin-confirm"]').click()
            cy.contains('[data-testid="admin-report"]', 'Delete this comment').should('not.exist')
            reportCard(title).find('[data-testid="report-delete"]').click()
            cy.get('[data-testid="admin-confirm"]').click()
            cy.contains('[data-testid="admin-report"]', title).should('not.exist')

            cy.request({ url: api(`/articles/${post.id}`), failOnStatusCode: false })
              .its('status').should('eq', 404)
            cy.request(api('/admin/reports?status=resolved')).its('body')
              .then((reports) => expect(reports.map(r => r.target.post_id)).not.to.include(post.id))
          })
        })
      })
    })
  })

  it('an admin deletes anyone\'s post and comment from the feed', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Feed delete, by ${author.username}` }).then((post) => {
        cy.apiComment(post.id, '<p>A comment an admin removes</p>')
        signupAdmin().then(() => {
          cy.visit(`/profile/${author.username}`)
          cy.get('[data-testid="comment-button"]').click()
          dialog().within(() => {
            cy.get('[data-testid="comment-report"]').should('exist')
            cy.get('[data-testid="comment-delete"]').click()
          })
          cy.get('[data-testid="comment-delete-confirm"]').click()
          dialog().find('[data-testid="comments-empty"]').should('exist')
          dialog().find('button').contains('Close').click()

          cy.get('[data-testid="admin-delete-post"]').click()
          cy.get('[data-testid="post-delete-confirm"]').click()
          cy.get('[data-testid="post-card"]').should('not.exist')
        })
      })
    })
  })

  it('a banned author is logged out everywhere and cannot log in; the report stays open', () => {
    cy.apiSignup().then((author) => {
      const title = `Post of a banned author, ${author.username}`
      cy.getCookie('session_id').then(({ value: authorSession }) => {
        cy.apiCreatePost({ title }).then((post) => {
          cy.apiSignup().then(() => cy.apiReport({ postId: post.id }, 'spam'))
          signupAdmin().then((admin) => {
            cy.visit('/admin')
            reportCard(title).find('[data-testid="report-ban"]').click()
            cy.get('[data-testid="admin-confirm"]').click()
            reportCard(title).within(() => {
              cy.get('[data-testid="admin-report-banned"]').should('exist')
              cy.get('[data-testid="report-dismiss"]').should('exist')   // still open
            })

            // The author's existing session no longer works.
            cy.clearCookies()
            cy.setCookie('session_id', authorSession)
            cy.request({ url: api('/me'), failOnStatusCode: false }).its('status').should('eq', 401)

            // Nor does logging in again.
            cy.clearCookies()
            cy.visit('/login')
            cy.get('[data-testid="login-email"]').type(author.email)
            cy.get('[data-testid="login-password"]').type(author.password)
            cy.get('[data-testid="login-submit"]').click()
            cy.get('[data-testid="login-error"]').should('contain', 'This account has been suspended')

            // Unban from the Users tab: the author can log in again.
            cy.apiLogin(admin)
            cy.visit('/admin')
            cy.get('[data-testid="admin-tab-users"]').click()
            cy.get('[data-testid="admin-banned-only"]').click()
            cy.get('[data-testid="admin-user-search"]').type(author.username)
            cy.contains('[data-testid="admin-user-row"]', author.username)
              .find('[data-testid="admin-user-ban"]').should('have.text', 'Unban').click()
            cy.contains('[data-testid="admin-user-row"]', author.username).should('not.exist')
            cy.apiLogin(author).its('username').should('eq', author.username)
          })
        })
      })
    })
  })

  it('only an admin gets the admin page and API', () => {
    cy.apiSignup().then(() => {
      cy.visit('/')
      cy.get('[data-testid="nav-logout"]').should('exist')        // logged in...
      cy.get('[data-testid="nav-admin"]').should('not.exist')     // ...but not an admin
      cy.visit('/admin')
      cy.get('[data-testid="admin-forbidden"]').should('contain', 'Admins only')
      cy.request({ url: api('/admin/reports'), failOnStatusCode: false }).its('status').should('eq', 403)
      cy.request({ method: 'POST', url: api('/admin/users/1/ban'), failOnStatusCode: false })
        .its('status').should('eq', 403)
    })
    cy.clearCookies()
    cy.visit('/admin')
    cy.get('[data-testid="admin-forbidden"]').should('exist')
    cy.visit('/')
    cy.get('[data-testid="post-card"]').should('exist')
    cy.get('[data-testid="report-post"]').should('not.exist')    // visitors cannot report
  })

  it('the admin page fits a phone', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `A long-winded title for a phone screen, by ${author.username}` }).then((post) => {
        cy.apiSignup().then(() => cy.apiReport({ postId: post.id }, 'other', 'x'.repeat(300)))
        signupAdmin().then(() => {
          cy.viewport('iphone-x')
          cy.visit('/admin')
          reportCard(author.username).should('be.visible')
          for (const tab of ['reports', 'users']) {
            cy.get(`[data-testid="admin-tab-${tab}"]`).click()
            cy.document().then((doc) => {
              const { scrollWidth, clientWidth } = doc.documentElement
              expect(scrollWidth, `${tab}: page width vs window width`).to.be.at.most(clientWidth)
            })
          }
        })
      })
    })
  })
})
