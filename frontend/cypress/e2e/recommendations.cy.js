// The home page's sidebar: trending tags (the last 24 hours) and who to follow
// (friends of friends, then shared tags, then the most followed), on real MySQL.
describe('home sidebar', () => {
  const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`
  const suggested = (username) => cy.get(`[data-testid="suggested-user"][data-username="${username}"]`)

  it('suggests a friend of a friend, with the reason, and Follow takes them off the list', () => {
    // apiSignup logs in as the user it creates, so each follow is made by the newest one.
    cy.apiSignup().then((target) => {
      cy.apiSignup().then((friend) => {
        cy.apiFollow(target.id)                     // friend -> target
        cy.apiSignup().then((viewer) => {
          cy.apiFollow(friend.id)                   // viewer -> friend

          cy.visit('/')
          cy.get('[data-testid="who-to-follow"]').should('be.visible')
          suggested(target.username)
            .should('contain', target.name)
            .find('[data-testid="suggested-reason"]')
            .should('have.text', 'Followed by 1 person you follow')
          // Someone the viewer already follows, and the viewer, are never suggested.
          suggested(friend.username).should('not.exist')
          suggested(viewer.username).should('not.exist')

          suggested(target.username).find('[data-testid="suggested-follow"]').click()
          suggested(target.username).should('not.exist')
          cy.request(api(`/users/${target.username}/followers`)).its('body')
            .should((followers) => expect(followers.map((u) => u.username)).to.include(viewer.username))
        })
      })
    })
  })

  it('shows a tag from the last 24 hours, and the chip opens its posts', () => {
    const tag = `trend${Date.now()}`
    cy.apiSignup().then(() => {
      // Three posts, so the tag is near the top whatever other specs posted today.
      ;[1, 2, 3].forEach((n) => cy.apiCreatePost({ title: `Trending ${n}`, tags: [tag] }))

      cy.request(api('/tags/trending?hours=24&limit=20')).its('body')
        .should((tags) => expect(tags).to.deep.include({ name: tag, post_count: 3 }))

      cy.visit('/')
      cy.get('[data-testid="trending-tags"]').should('contain', 'Trending (24h)')
      cy.contains('[data-testid="trending-tag"]', `#${tag}`)
        .should('have.attr', 'title', '3 posts in the last 24 hours')
        .click()
      cy.location('pathname').should('eq', `/tag/${tag}`)
      cy.get('[data-testid="post-card"]').should('have.length', 3)
    })
  })

  it('a guest gets the most followed, without Follow buttons', () => {
    cy.apiSignup().then((popular) => {
      cy.apiSignup().then(() => {
        cy.apiFollow(popular.id)                    // so someone is followed
        cy.clearCookies()

        cy.visit('/')
        cy.get('[data-testid="suggested-user"]').should('have.length.at.least', 1)
        cy.get('[data-testid="suggested-reason"]').each(([reason]) => {
          expect(reason.textContent).to.match(/^\d+ followers?$/)
        })
        cy.get('[data-testid="suggested-follow"]').should('not.exist')
      })
    })
  })

  it('marks an AI agent in the suggestions', () => {
    // A guest gets the most followed: make an agent the most followed of all.
    const followers = 6
    cy.request(api('/users/carlos_ai')).its('body').then((agent) => {
      Cypress._.times(followers, () => {
        cy.apiSignup().then(() => cy.apiFollow(agent.id))
      })
      cy.clearCookies()
      cy.visit('/')
      suggested('carlos_ai')
        .should('contain', 'AI agent')
        .find('[data-testid="suggested-reason"]')
        .invoke('text')
        .should('match', /^\d+ followers$/)
    })
  })
})
