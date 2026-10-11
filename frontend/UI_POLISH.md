# Frontend polish review

Branch: `ui/frontend-polish`; base: `e5f6159`; worktree: `PulseNet-ui-frontend-polish`.

## First pass — changes

- A central, system-aware MUI theme replaces conflicting global light/dark styles. Shared page gutters, readable surfaces, typography, borders, and focus states retain the blue/orange identity.
- Mobile branding, active desktop navigation, semantic author links, wrapped post actions, and consistent profile/sidebar surfaces improve the existing layouts. Feed columns and sidebar breakpoints are preserved.
- API reads consistently reject HTTP errors through the existing API helper. Feed/detail/search/sidebar failures have useful feedback and retry behavior; paging and search ignore stale responses.
- Profile follow errors stay inline. Auth forms support Enter and autocomplete, preserve rejected input, and guard duplicate submissions. Uploads block publish/save until completion. Admin requests distinguish loading from empty results and ignore stale filters.
- Quill and comment/report inputs have accessible names. Keyboard navigation, dialog focus return, long text, and contrast are checked without adding dependencies.

No routes, API wire contracts, existing testids, backend code, database code, agent runtime, deployment configuration, CI configuration, dependencies, or existing test specs were changed. The small keyed feed boundary fixes filter/viewer pagination resets; no broad component refactor was performed.

## First pass — verification

Baseline inventory: **45 existing tests in 16 specs**, with no skips or exclusive tests.

Added coverage:
- `ui_states.cy.js`: 17 request/race/recovery and submission cases.
- `ui_visual.cy.js`: 6 viewport/theme combinations, covering 15 screen/state captures each, with overflow and rendered text-contrast assertions.
- `ui_keyboard.cy.js`: 1 native keyboard navigation/focus case.

Final full regression: **69/69 passing in 19 specs**, completed in **2m 51s**. All **45 original tests passed unchanged**, and all **24 added tests passed**. **0 failures, 0 pending, 0 skipped**. The full suite was run once at the final gate; development used targeted specs only.

Frontend lint and the production build passed. The existing responsive spec passed all 4 cases. Native keyboard activation, menu navigation, dialog focus return, labels, rendered text contrast, and horizontal overflow checks passed. No separate accessibility runner was present.

A subsequent targeted visual-spec run passed **6/6** and verified the new capture synchronization: profile screenshots wait for feed content, and captures wait for loading and click ripples to finish. No application code or existing test expectations changed after the passing full regression.

Visual review completed: **90 browser captures across 15 screens/states**, using **375px, 768px, 1280px × light/dark**. Includes Home/feed/sidebar/TopBar, post detail/comments, human and AI profiles, post editor, profile editor, login errors, signup, forgot-password errors, valid/missing reset links, admin reports/users, and empty/error feeds.

The Cypress browser produces the captures for manual inspection under `cypress/screenshots/ui_visual.cy.js/`. These generated images are ignored by Git. The final full regression log is `cypress/logs/ui-polish-full.log`; the targeted capture rerun is `cypress/logs/ui-polish-visual-final.log`.

The direct browser connector was unavailable; visual review uses screenshots from the actual application running in Cypress. Native Chromium keyboard events are used because Cypress 13's synthetic Enter does not natively activate ordinary buttons.

## Settings, branding, and profile follow-up (2026-10-11)

Baseline for this follow-up: **69 tests in 19 specs**, at `7cfd3f2`.

- Added an always-visible Settings gear with Light / Dark / System and authenticated Logout. Existing desktop/mobile logout controls and testids are retained; the same confirmation and session API handles both entry points.
- Theme choice persists in `pulsenet.theme` in localStorage. System responds to live OS changes; explicit preferences override them. Invalid/unavailable storage falls back safely, and changes remain usable in memory.
- Added one bundled pulse/network SVG for the TopBar and favicon. Added a bundled decorative blue/orange profile cover; profiles need no new data, upload UI, or API calls.
- The avatar overlaps the cover while profile content, follow/edit controls, counts, agent badges/persona, and feed behavior remain intact.
- The TopBar change is limited to the brand, Settings entry point, accessible logout title, and placement that keeps the existing mobile keyboard order.

Added 10 focused tests in `settings_brand.cy.js`: branding/guest settings, persistence/draft retention, live System vs explicit overrides, invalid and unavailable storage, native keyboard/focus, both logout modes, and two responsive profile cases. Overlap checks use broad proportions, not exact pixels. The existing visual spec gains Settings and logout captures without changing its test count. Its contrast assertions retain their original thresholds and now retry while MUI enabled/focus color transitions settle; the first targeted run exposed a transient label color. No existing behavior assertions were removed or weakened.

Frontend lint and the production build passed. The full Cypress suite ran once at the final gate and passed **79/79 tests across 20 specs in 4m 33s**: **69 existing tests passed (including all 45 original tests), 10 new tests passed, 0 failures, 0 pending, 0 skipped**. No tests were removed or made exclusive. Existing responsive checks and native keyboard/focus, contrast, and overflow checks passed; no separate accessibility runner exists.

During development, the targeted run passed all 10 new tests and 11 related existing tests. Two of the 6 visual combinations initially failed on transient enabled-state label/button colors; after adding assertion retries without changing contrast thresholds, the targeted visual rerun passed **6/6**. The final full regression includes this correction.

Manual visual review completed for **102 browser captures** covering 17 screens/states at **375px, 768px, and 1280px in both light and dark themes**. This includes Settings/logout, Home/TopBar/sidebar, human and agent profiles, post/comments, editors, auth/reset, admin, long text, and empty/error states. Logs: `cypress/logs/settings-targeted.log`, `cypress/logs/settings-visual-retry.log`, and `cypress/logs/settings-full.log`.

## Post-submission follow-ups

- Defer popular/most-traffic posts: existing paginated data has likes/comments but no traffic metric or complete ranking. Do not present a partial-page sort as a site-wide popularity feature.
- Separate post-preview/detail/management responsibilities in SinglePost only with dedicated regression coverage.
- Revisit SearchBar naming/responsibilities and comments organization as a deliberate refactor.
- Consider route/editor code splitting for the existing large-bundle warning (follow-up entry about 881 KB minified / 269 KB gzip).
- Broaden automated accessibility checks beyond the focused keyboard, naming, contrast, and overflow checks included here.

No merge or push to main is part of this pass. Concurrent edits in the main checkout are outside this branch and have been left untouched.
