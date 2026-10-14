import { mockShell, viewer } from '../support/uiFixtures'

// Admin > AI Activity. The first tests run on the real stack, so migration 009, the
// agent turn's link to its target and the activity UNION run on MySQL: an agent's
// turns come from manage.py agent-tick (the agentTick task, LLM off, so a like or a
// follow), a person's AI help from the fake LLM. The rest answer the page from
// fixtures, for the states the real data cannot make on demand.
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`
const AGENT = 'rex_ai'   // no other spec gives this agent a turn

const signupAdmin = () =>
  cy.apiSignup().then((admin) => cy.task('makeAdmin', admin.username).then(() => admin))

const openTab = () => {
  cy.visit('/admin')
  cy.get('[data-testid="admin-tab-ai-activity"]').click()
}

const rows = () => cy.get('[data-testid="ai-activity-row"]')

// A spy on the page's requests with this query. In the dev server StrictMode sends
// the first one twice, so each wait names the request it means.
const when = (query) => cy.intercept({ method: 'GET', pathname: '/api/admin/ai-activity', query })

// The rows' times (their datetime attributes), as numbers, in page order.
const times = () => rows().find('time').then(($t) => [...$t].map((t) => Date.parse(t.getAttribute('datetime'))))

describe('admin AI activity, on the real stack', () => {
  it('shows an agent\'s like and follow and a person\'s AI help, links them, filters and sorts', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Something for the agents, by ${author.username}` })
      cy.task('agentTick', AGENT).then((first) => {
        const liked = /liked \(like (\d+)\)/.exec(first)
        expect(liked, first).to.not.equal(null)
        const likedId = Number(liked[1])
        // The next turn follows the author of the post it liked.
        cy.task('agentTick', AGENT).then((second) => {
          const followed = /followed \(follow (\d+)\)/.exec(second)
          expect(followed, second).to.not.equal(null)

          signupAdmin().then((admin) => {
            cy.request('POST', api('/ai/correct'), { text: 'teh text', format: 'text' })
            when({ type: 'all', sort: 'newest', page: '1', per_page: '25' }).as('all')
            openTab()
            cy.wait('@all')
            rows().should('have.length.at.least', 3)
            times().then((t) => expect(t, 'newest first').to.deep.equal([...t].sort((a, b) => b - a)))

            // The person's AI help: used, by the admin, linked to their profile.
            when({ type: 'ai_assist' }).as('assist')
            cy.get('[data-testid="ai-activity-type"]').select('ai_assist')
            cy.wait('@assist')
            rows().should('have.length.at.least', 1).first().within(() => {
              cy.get('[data-testid="ai-activity-text"]').should('contain', 'used AI Grammar Correction')
              cy.get('[data-testid="ai-activity-actor"]')
                .should('have.attr', 'href', `/profile/${admin.username}`)
              cy.get('[data-testid="ai-activity-view-post"]').should('not.exist')
            })

            // The agent's follow names who it followed.
            when({ type: 'followed' }).as('follows')
            cy.get('[data-testid="ai-activity-type"]').select('followed')
            cy.wait('@follows')
            cy.contains('[data-testid="ai-activity-row"]', 'followed').within(() => {
              cy.get('[data-testid="ai-activity-actor"]').should('have.attr', 'href', `/profile/${AGENT}`)
              cy.get('[data-testid="ai-activity-target"]').should('have.attr', 'href').and('match', /^\/profile\//)
            })

            // The like links its post, and View post opens it.
            when({ type: 'liked' }).as('likes')
            cy.get('[data-testid="ai-activity-type"]').select('liked')
            cy.wait('@likes')
            rows().should('have.length.at.least', 1).each(($row) => expect($row.attr('data-type')).to.equal('liked'))
            cy.get(`[data-testid="ai-activity-view-post"][href="/post/${likedId}"]`).first().click()
            cy.location('pathname').should('eq', `/post/${likedId}`)
            cy.get('[data-testid="post-card"]').should('have.length', 1).and('be.visible')
            cy.go('back')

            // Oldest first asks for it, and the times go up.
            cy.get('[data-testid="admin-tab-ai-activity"]').click()
            rows().should('have.length.at.least', 3)
            when({ type: 'all', sort: 'oldest' }).as('oldest')
            cy.get('[data-testid="ai-activity-sort"]').select('oldest')
            cy.wait('@oldest')
            rows().should('have.length.at.least', 3)
            times().then((t) => expect(t, 'oldest first').to.deep.equal([...t].sort((a, b) => a - b)))
          })
        })
      })
    })
  })

  it('is for admins only', () => {
    cy.apiSignup().then(() => {
      cy.request({ url: api('/admin/ai-activity'), failOnStatusCode: false }).its('status').should('eq', 403)
      cy.visit('/admin')
      cy.get('[data-testid="admin-forbidden"]').should('contain', 'Admins only')
      cy.get('[data-testid="admin-tab-ai-activity"]').should('not.exist')
    })
    cy.clearCookies()
    cy.request({ url: api('/admin/ai-activity'), failOnStatusCode: false }).its('status').should('eq', 401)
  })
})

// ─── From fixtures ───────────────────────────────────────────────────────────

const AT = '2026-10-15T16:00:00+00:00'
const mei = { id: 11, username: 'mei_ai', name: 'Mei Tanaka', is_agent: true }
const nadav = { id: 2, username: 'nadav', name: 'Nadav', is_agent: false }
const post = { id: 39, title: 'Practical Baselines for ML' }
const event = (id, type, over = {}) => ({
  id, source: type.startsWith('ai_') ? 'ai_assist' : 'agent', type, created_at: AT,
  actor: type.startsWith('ai_') ? nadav : mei, post: null, comment_id: null, target_user: null,
  status: type.startsWith('ai_') ? 'ok' : null, ...over,
})
const page = (items, over = {}) => ({ items, page: 1, per_page: 25, total: items.length, has_more: false, ...over })

const EVERY_KIND = [
  event('agent-1', 'posted', { post }),
  event('agent-2', 'commented', { post, comment_id: 90 }),
  event('agent-3', 'replied', { post, comment_id: 91 }),
  event('agent-4', 'liked', { post }),
  event('agent-5', 'followed', { target_user: nadav }),
  event('ai_assist-1', 'ai_correct'),
  event('ai_assist-2', 'ai_suggest_post', { status: 'error' }),
  event('ai_assist-3', 'ai_suggest_comment', { status: 'over_limit' }),
  event('ai_assist-4', 'ai_suggest_comment', { status: 'timeout' }),
  // A deleted person, a deleted follow target, a turn with no post (before 009).
  event('ai_assist-5', 'ai_correct', { actor: null }),
  event('agent-6', 'followed', { target_user: null }),
  event('agent-7', 'liked'),
]

describe('admin AI activity, from fixtures', () => {
  beforeEach(() => mockShell({ ...viewer, role: 'admin' }))

  const row = (id) => cy.get(`[data-testid="ai-activity-row"]`).eq(EVERY_KIND.findIndex((e) => e.id === id))

  it('says what each event was, with exact times and links, and never more than it knows', () => {
    cy.intercept('GET', '**/api/admin/ai-activity*', page(EVERY_KIND)).as('activity')
    openTab()
    cy.wait('@activity')
    rows().should('have.length', EVERY_KIND.length)
    cy.get('[data-testid="ai-activity-time"]').first()
      .should('have.attr', 'datetime', AT)
      .invoke('text').should('match', /^\d{2}\/\d{2}\/\d{4}, \d{2}:\d{2}$/)

    const sentences = {
      'agent-1': 'Mei Tanaka @mei_ai created a post',
      'agent-2': 'Mei Tanaka @mei_ai commented on a post',
      'agent-3': 'Mei Tanaka @mei_ai replied to a comment',
      'agent-4': 'Mei Tanaka @mei_ai liked a post',
      'agent-5': 'Mei Tanaka @mei_ai followed Nadav @nadav',
      'ai_assist-1': 'Nadav @nadav used AI Grammar Correction',
      'ai_assist-2': 'Nadav @nadav attempted AI Post Suggestion',
      'ai_assist-3': 'Nadav @nadav attempted AI Comment Suggestion',
      'ai_assist-4': 'Nadav @nadav attempted AI Comment Suggestion',
      'ai_assist-5': 'Deleted user used AI Grammar Correction',
      'agent-6': 'Mei Tanaka @mei_ai followed Deleted user',
    }
    for (const [id, text] of Object.entries(sentences)) {
      row(id).find('[data-testid="ai-activity-text"]').invoke('text')
        .then((t) => expect(t.replace(/\s+/g, ' ').trim(), id).to.equal(text))
    }

    // Posts: the title, and View post to /post/:id.
    for (const id of ['agent-1', 'agent-2', 'agent-3', 'agent-4']) {
      row(id).find('[data-testid="ai-activity-view-post"]').should('have.attr', 'href', '/post/39')
      row(id).find('[data-testid="ai-activity-post-title"]').should('contain', '“Practical Baselines for ML”')
    }
    row('agent-2').find('[data-testid="ai-activity-post-title"]').should('contain', 'on “Practical')
    // An agent is marked, and its name links its profile.
    row('agent-1').should('contain', 'AI agent')
    row('agent-1').find('[data-testid="ai-activity-actor"]').should('have.attr', 'href', '/profile/mei_ai')
    row('agent-5').find('[data-testid="ai-activity-target"]').should('have.attr', 'href', '/profile/nadav')

    // A helper that did not work was only attempted, and says why.
    row('ai_assist-1').find('[data-testid="ai-activity-status"]').should('not.exist')
    row('ai_assist-2').find('[data-testid="ai-activity-status"]').should('have.text', 'failed')
    row('ai_assist-3').find('[data-testid="ai-activity-status"]').should('have.text', 'limit reached, not run')
    row('ai_assist-4').find('[data-testid="ai-activity-status"]').should('have.text', 'timed out')

    // Deleted users: a label, never a link or a name.
    row('ai_assist-5').find('[data-testid="ai-activity-actor-deleted"]').should('have.text', 'Deleted user')
    row('ai_assist-5').find('a').should('not.exist')
    row('agent-6').find('[data-testid="ai-activity-target-deleted"]').should('have.text', 'Deleted user')
    row('agent-6').find('[data-testid="ai-activity-target"]').should('not.exist')
    // No post recorded: no link to a post that cannot open.
    row('agent-7').find('[data-testid="ai-activity-view-post"]').should('not.exist')
    row('agent-7').find('[data-testid="ai-activity-no-post"]').should('contain', 'deleted or not recorded')

    cy.get('[data-testid="ai-activity"]').invoke('text').should('not.match', /applied|published/i)
    cy.get('[data-testid="ai-activity-count"]').should('have.text', `Showing ${EVERY_KIND.length} of ${EVERY_KIND.length}`)
  })

  it('loads more without repeating a row', () => {
    const first = [event('agent-1', 'posted', { post }), event('agent-2', 'liked', { post })]
    // New activity came in: page 2 starts with the last row of page 1 again.
    const second = [event('agent-2', 'liked', { post }), event('agent-3', 'followed', { target_user: nadav })]
    cy.intercept('GET', '**/api/admin/ai-activity*', (req) => {
      const p = Number(new URL(req.url).searchParams.get('page'))
      req.reply(p === 1 ? page(first, { total: 3, has_more: true }) : page(second, { page: 2, total: 3 }))
    })
    when({ page: '2', per_page: '25' }).as('page2')
    openTab()
    cy.get('[data-testid="ai-activity-count"]').should('have.text', 'Showing 2 of 3')
    cy.get('[data-testid="ai-activity-more"]').click()
    cy.wait('@page2')
    rows().should('have.length', 3)
    cy.get('[data-testid="ai-activity-count"]').should('have.text', 'Showing 3 of 3')
    cy.get('[data-testid="ai-activity-more"]').should('not.exist')
  })

  it('shows an error with Retry, and an empty filter', () => {
    let down = true
    cy.intercept('GET', '**/api/admin/ai-activity*', (req) => {
      if (down) req.reply({ statusCode: 503, body: { error: 'Database unavailable' } })
      else if (req.url.includes('type=followed')) req.reply(page([]))
      else req.reply(page([event('agent-1', 'posted', { post })]))
    })
    openTab()
    cy.get('[data-testid="ai-activity-error"]').should('contain', 'Database unavailable')
      .then(() => { down = false })
    cy.get('[data-testid="ai-activity-error"]').contains('button', 'Retry').click()
    rows().should('have.length', 1)
    cy.get('[data-testid="ai-activity-error"]').should('not.exist')

    cy.get('[data-testid="ai-activity-type"]').select('followed')
    cy.get('[data-testid="ai-activity-empty"]').should('have.text', 'No follows by AI agents yet.')
    rows().should('not.exist')
  })

  it('a slow answer for an old filter never replaces the new one', () => {
    cy.intercept('GET', '**/api/admin/ai-activity*', (req) => {
      if (req.url.includes('type=all')) {
        req.reply({ delay: 1500, body: page([event('agent-1', 'posted', { post })]) })
      } else {
        req.reply(page([event('agent-9', 'liked', { post })]))
      }
    })
    openTab()
    cy.get('[data-testid="ai-activity-type"]').select('liked')
    rows().should('have.length', 1).first().should('have.attr', 'data-type', 'liked')
    cy.wait(1800)   // the slow 'all' answer has arrived by now
    rows().should('have.length', 1).first().should('have.attr', 'data-type', 'liked')
  })

  it('works from the keyboard: the tab, the filters and View post', () => {
    cy.intercept('GET', '**/api/admin/ai-activity*', page([event('agent-1', 'posted', { post })])).as('activity')
    cy.visit('/admin')
    cy.get('[data-testid="admin-tab-reports"]').focus()
    press('ArrowRight', 'ArrowRight', 39)
    press('ArrowRight', 'ArrowRight', 39)
    cy.focused().should('have.attr', 'data-testid', 'admin-tab-ai-activity')
    press('Enter', 'Enter', 13)
    cy.wait('@activity')
    press('Tab', 'Tab', 9)
    cy.focused().should('have.attr', 'data-testid', 'ai-activity-type')
    press('Tab', 'Tab', 9)
    cy.focused().should('have.attr', 'data-testid', 'ai-activity-sort')
    cy.get('[data-testid="ai-activity-view-post"]').focus()
    press('Enter', 'Enter', 13)
    cy.location('pathname').should('eq', '/post/39')
  })

  it('fits a phone', () => {
    cy.viewport('iphone-x')
    const long = { id: 40, title: 'A very long title about practical baselines for machine learning '.repeat(3) }
    cy.intercept('GET', '**/api/admin/ai-activity*',
      page([event('agent-1', 'commented', { post: long, comment_id: 9 }), ...EVERY_KIND.slice(4, 8)])).as('activity')
    openTab()
    cy.wait('@activity')
    rows().should('have.length', 5)
    cy.get('[data-testid="ai-activity-view-post"]').should('be.visible')
    cy.get('[data-testid="ai-activity-type"]').should('be.visible')
    cy.get('[data-testid="ai-activity-sort"]').should('be.visible')
    cy.document().then((doc) => {
      const { scrollWidth, clientWidth } = doc.documentElement
      expect(scrollWidth, 'page width vs window width').to.be.at.most(clientWidth)
    })
  })
})

// Native key events (as ui_keyboard.cy.js): Cypress' type() does not move focus with Tab.
function press(key, code, windowsVirtualKeyCode) {
  ['keyDown', 'keyUp'].forEach((type) => {
    cy.then(() => Cypress.automation('remote:debugger:protocol', {
      command: 'Input.dispatchKeyEvent',
      params: { type, key, code, windowsVirtualKeyCode,
        ...(type === 'keyDown' && key === 'Enter' ? { text: '\r', unmodifiedText: '\r' } : {}) },
    }))
  })
}
