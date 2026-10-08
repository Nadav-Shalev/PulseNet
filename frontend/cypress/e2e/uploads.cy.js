// Image upload: the backend answers a relative /uploads/<file> URL, which the page
// loads from its own origin (nginx on the EC2, the Vite proxy here). An absolute URL
// built from the request's host lost the :8080 behind nginx and broke on the live site.

// A 1x1 PNG.
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

const loaded = ($img) => {
  expect($img[0].naturalWidth, `${$img.attr('src')} loaded`).to.be.greaterThan(0)
}

describe('image upload', () => {
  it('stores a relative URL, and the image shows in the editor and the feed', () => {
    cy.apiSignup()
    cy.visit('/new-post')
    cy.get('input[type="file"]').selectFile(
      { contents: Cypress.Buffer.from(PNG, 'base64'), fileName: 'cover.png', mimeType: 'image/png' },
      { force: true },
    )

    cy.get('img[alt="cover preview"]').should('have.attr', 'src').and('match', /^\/uploads\/[0-9a-f]{32}\.png$/)
    cy.get('img[alt="cover preview"]').should(loaded)

    cy.get('img[alt="cover preview"]').invoke('attr', 'src').then((src) => {
      const title = `Cover upload ${Date.now()}`
      cy.apiCreatePost({ title, mainImage: src })
      cy.visit('/')
      cy.contains('[data-testid="post-card"]', title).find(`img[src="${src}"]`).should(loaded)
    })
  })
})
