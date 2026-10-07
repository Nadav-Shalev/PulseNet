// Shared Cypress commands.
//
// The api* commands set up state by calling the backend directly (no UI), so each
// spec drives the UI only for the flow it actually tests. cy.request keeps the
// session cookie the API sets, so after apiSignup / apiLogin the app is logged in
// as that user. A non-2xx response fails the test with the API's error.

const api = (route) => `${Cypress.env('apiBaseUrl')}${route}`

let sequence = 0
const unique = () => `${Date.now()}_${(sequence += 1)}`

// Create a user and log in as them. Yields the user, including id and password.
//   cy.apiSignup().then((user) => ...)
//   cy.apiSignup({ bio: 'custom bio' })
Cypress.Commands.add('apiSignup', (overrides = {}) => {
  const stamp = unique()
  const user = {
    name: `E2E User ${stamp}`,
    username: `e2e_${stamp}`,
    email: `e2e_${stamp}@example.com`,
    bio: 'Created by cy.apiSignup',
    password: 'E2ePass123!',
    ...overrides,
  }
  return cy.request('POST', api('/users'), user).then(({ body }) => ({ ...user, id: body.id }))
})

// Log in as an existing user. Yields the user JSON from /api/login.
//   cy.apiLogin({ email, password })
Cypress.Commands.add('apiLogin', ({ email, password }) =>
  cy.request('POST', api('/login'), { email, password }).its('body'),
)

// Create a post as the logged-in user. Yields the created post (DEV.to shape, has id).
//   cy.apiCreatePost({ title: 'Hello', bodyHtml: '<p>Hi</p>', tags: ['react'] })
Cypress.Commands.add('apiCreatePost', ({ title, bodyHtml, tags = [], mainImage = '' } = {}) => {
  const article = {
    title: title ?? `E2E post ${unique()}`,
    body_html: bodyHtml ?? '<p>Created by cy.apiCreatePost</p>',
    tags,
    main_image: mainImage,
  }
  return cy.request('POST', api('/articles'), { article }).its('body')
})

// Follow a user as the logged-in user. The follower comes from the session cookie.
//   cy.apiFollow(author.id)
Cypress.Commands.add('apiFollow', (userId) =>
  cy.request('POST', api(`/users/${userId}/follow`)).its('body'),
)
