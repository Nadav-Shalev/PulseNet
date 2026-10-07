// A user's email is visible only to that user. Every public endpoint is called
// against the real database (the backend unit tests use a fake one), so this also
// proves the queries without the email column run on MySQL.
const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

const expectNoEmail = (route, body, users) => {
  const json = JSON.stringify(body)
  expect(json, `${route} has no "email" field`).not.to.contain('"email"')
  users.forEach(({ email }) => expect(json, `${route} hides ${email}`).not.to.contain(email))
}

describe('email privacy', () => {
  it('public responses never contain an email; only /api/me does', () => {
    cy.apiSignup().then((author) => {
      cy.apiCreatePost({ title: `Privacy check by ${author.username}` }).then((post) => {
        expectNoEmail('POST /articles', post, [author])

        // A second user follows the author, so the follow lists and the following
        // feed are not empty. apiSignup leaves us logged in as the reader.
        cy.apiSignup().then((reader) => {
          const users = [author, reader]
          cy.request('POST', api(`/users/${author.id}/follow`))

          const publicRoutes = [
            '/articles',
            `/articles?username=${author.username}`,
            '/articles?feed=following',
            `/articles/${post.id}`,
            `/users?q=${author.username}`,
            `/users/search?q=${author.username}`,
            `/users/${author.username}`,
            `/users/${author.username}/followers`,
            `/users/${reader.username}/following`,
          ]
          publicRoutes.forEach((route) => {
            cy.request(api(route)).then(({ body }) => {
              expect(JSON.stringify(body), `${route} is not empty`)
                .to.match(new RegExp(`${author.username}|${reader.username}`))
              expectNoEmail(route, body, users)
            })
          })

          // Searching by an address must not reveal whose it is.
          cy.request(api(`/users/search?q=${encodeURIComponent(author.email)}`))
            .its('body').should('deep.equal', [])
          cy.request(api(`/users?q=${encodeURIComponent(author.email)}`))
            .its('body').should('deep.equal', [])

          cy.request(api('/me')).its('body.email').should('equal', reader.email)
        })
      })
    })
  })
})
