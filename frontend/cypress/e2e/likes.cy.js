// Liking posts, against the real database (the backend tests use a fake one, so
// this is what runs the likes SQL on MySQL): the count and the filled heart come
// back from the feed query after a reload, and every feed mode reports them.
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

describe('likes', () => {
  const card = () => cy.get('[data-testid="post-card"]').first()

  const expectLike = (count, pressed) => {
    cy.get('[data-testid="like-count"]').should('have.text', String(count))
    cy.get('[data-testid="like-button"]').should('have.attr', 'aria-pressed', String(pressed))
  }

  it('a reader likes and unlikes a post from its card, and both survive a reload', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Like me, by ${author.username}` })
      cy.apiSignup() // now logged in as the reader
      cy.visit(`/profile/${author.username}`)

      card().within(() => {
        expectLike(0, false)
        cy.get('[data-testid="like-button"]').click()
        expectLike(1, true)
      })

      cy.reload()
      card().within(() => {
        expectLike(1, true) // liked_by_me, read back by the feed query
        cy.get('[data-testid="like-button"]').click()
        expectLike(0, false)
      })

      cy.reload()
      card().within(() => expectLike(0, false))
    })
  })

  it('a logged-out visitor sees the count, and the heart sends them to log in', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost().then((post) => {
        cy.apiSignup()
        cy.apiLike(post.id)
        cy.clearCookies()

        cy.visit(`/profile/${author.username}`)
        card().within(() => {
          expectLike(1, false)
          cy.get('[data-testid="like-button"]').click()
        })
        cy.location('pathname').should('eq', '/login')
      })
    })
  })

  it('every feed reports likes, liking twice counts once, and a liked post can be deleted', () => {
    const tag = `liketag${Date.now()}`
    const findPost = (body, id) => (Array.isArray(body) ? body.find((p) => p.id === id) : body)
    const expectLikes = (route, id, likeCount, likedByMe) =>
      cy.request(api(route)).its('body').then((body) => {
        const post = findPost(body, id)
        expect(post, `${route} has the post`).to.exist
        expect(post.like_count, `${route} like_count`).to.equal(likeCount)
        expect(post.liked_by_me, `${route} liked_by_me`).to.equal(likedByMe)
      })

    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ tags: [tag] }).then((post) => {
        cy.apiSignup() // the reader
        cy.apiFollow(author.id)

        // INSERT IGNORE + the composite primary key: a second like changes nothing.
        cy.apiLike(post.id).should('deep.equal', { liked: true, like_count: 1 })
        cy.apiLike(post.id).should('deep.equal', { liked: true, like_count: 1 })

        const everyFeed = [
          '/articles',
          `/articles?username=${author.username}`,
          `/articles?tag=${tag}`,
          '/articles?feed=following',
          `/articles/${post.id}`,
        ]
        everyFeed.forEach((route) => expectLikes(route, post.id, 1, true))

        cy.request('DELETE', api(`/articles/${post.id}/like`))
          .its('body').should('deep.equal', { liked: false, like_count: 0 })
        expectLikes(`/articles?tag=${tag}`, post.id, 0, false)
        cy.apiLike(post.id)

        // Logged out, the count stays and liked_by_me is false.
        cy.clearCookies()
        ;['/articles', `/articles?tag=${tag}`, `/articles/${post.id}`]
          .forEach((route) => expectLikes(route, post.id, 1, false))

        // The author can still delete the liked post: ON DELETE CASCADE removes its likes.
        cy.apiLogin(author)
        cy.request('DELETE', api(`/articles/${post.id}`))
          .its('body').should('deep.equal', { deleted: true, id: post.id })
        cy.request({ url: api(`/articles/${post.id}`), failOnStatusCode: false })
          .its('status').should('equal', 404)
      })
    })
  })
})
