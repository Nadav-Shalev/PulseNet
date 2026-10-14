// Every page fits a 375px phone (iPhone X) without sideways scrolling, and the
// feed remains one column on phones and wide screens.
const LONG_WORD = 'averyveryverylongunbrokenwordthatcouldwidenthecardpastthescreen'

// The page is no wider than the window (clientWidth excludes a vertical scrollbar).
const expectNoSidewaysScroll = (page) => {
  cy.document().should((doc) => {
    const { scrollWidth, clientWidth } = doc.documentElement
    expect(scrollWidth, `${page}: page width vs window width`).to.be.at.most(clientWidth)
  })
}

// A card hides overflow, so a long word that does not wrap is clipped, not scrolled.
const expectCardsNotClipped = (page) => {
  cy.get('[data-testid="post-card"]').each(([card]) => {
    expect(card.scrollWidth, `${page}: card content width vs card width`).to.be.at.most(card.clientWidth)
  })
}

const left = (el) => Math.round(el.getBoundingClientRect().left)

describe('responsive layout', () => {
  let author

  beforeEach(() => {
    cy.apiSignup({ name: `Responsive ${LONG_WORD}` }).then((user) => {
      author = user
      cy.apiCreatePost({
        title: `Phone check ${LONG_WORD}`,
        bodyHtml: `<p>${LONG_WORD} https://example.com/a/very/long/path/that/does/not/break/at/all</p>`,
        tags: ['javascript', 'webdevelopment', 'beginners', 'react'],
      })
      cy.apiCreatePost({ title: 'Second phone post' })
    })
  })

  it('no page scrolls sideways at 375px', () => {
    cy.viewport('iphone-x')
    const pages = [
      ['/', '[data-testid="post-card"]'],
      ['/users', '[data-testid="users-table"] tbody tr'],
      [`/profile/${author.username}`, '[data-testid="post-card"]'],
      [`/user-posts/${author.username}`, '[data-testid="post-card"]'],
      ['/tag/react', '[data-testid="post-card"]'],
      ['/new-post', '.ql-editor'],
      ['/edit-profile', 'form, input'],
      ['/about', 'h1, h2, h3'],
    ]
    pages.forEach(([path, ready]) => {
      cy.visit(path)
      cy.get(ready).should('exist')
      expectNoSidewaysScroll(path)
      if (ready.includes('post-card')) expectCardsNotClipped(path)
    })

    cy.clearCookies()
    ;['/login', '/signup'].forEach((path) => {
      cy.visit(path)
      cy.get('input').should('exist')
      expectNoSidewaysScroll(path)
    })
  })

  it('the feed remains one column on a phone and desktop', () => {
    // should() retries until the layout settles, so a late re-render is not a failure.
    cy.viewport('iphone-x')
    cy.visit(`/user-posts/${author.username}`)
    cy.get('[data-testid="post-card"]').should('have.length', 2)
      .should(([first, second]) => expect(left(second), 'stacked cards').to.equal(left(first)))

    cy.viewport(1280, 800)
    cy.get('[data-testid="post-card"]')
      .should(([first, second]) => expect(left(second), 'stacked desktop cards').to.equal(left(first)))
  })

  it('on a phone the profile header stacks and a post opens full screen', () => {
    cy.viewport('iphone-x')
    cy.visit(`/profile/${author.username}`)

    cy.get('[data-testid="profile-header"] .MuiAvatar-root').then(([avatar]) => {
      cy.get('[data-testid="profile-name"]').should(([name]) => {
        expect(avatar.getBoundingClientRect().bottom, 'avatar above the name')
          .to.be.at.most(name.getBoundingClientRect().top)
      })
    })

    cy.contains('[data-testid="post-card"]', 'Phone check').find('[data-testid="comment-button"]').click()
    cy.get('[data-testid="post-dialog"] .MuiDialog-paper').should(([paper]) => {
      expect(paper.getBoundingClientRect().width, 'dialog width').to.equal(375)
    })
    cy.get('[data-testid="post-dialog"]').should('contain', LONG_WORD)
    expectNoSidewaysScroll('post dialog')
  })

  it('the home sidebar follows the feed on a phone and stays beside it on a wide screen', () => {
    const rect = (el) => el.getBoundingClientRect()
    cy.viewport('iphone-x')
    cy.visit('/')
    // The sidebar loads on its own: wait for it and for the feed.
    cy.get('[data-testid="trending-tag"]').should('exist')
    cy.get('[data-testid="post-card"]').should('exist')
    expectNoSidewaysScroll('/ with the sidebar')
    cy.get('[data-testid="home-sidebar"]').then(([side]) => {
      cy.get('[data-testid="post-card"]').last()
        .should(([card]) => expect(rect(side).top, 'sidebar after the feed').to.be.at.least(rect(card).bottom))
    })

    cy.viewport(1280, 800)
    cy.get('[data-testid="home-sidebar"]').then(([side]) => {
      cy.get('[data-testid="post-card"]').first()
        .should(([card]) => expect(rect(side).left, 'sidebar right of the feed').to.be.at.least(rect(card).right))
    })
  })
})
