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

## Vertical feeds and inline bodies (2026-10-11)

Baseline for this pass: **79 tests across 20 specs**, at `6376fb3`.

- All feeds now use a single vertical column, including Global/Following, profiles, user-post pages, and tags. Existing page widths, feed pagination, and sidebar breakpoints stay intact.
- Who to follow renders the first three API-ordered suggestions at every width and reveals the next loaded person after a successful follow.
- `PostBody` owns its viewport observer (200px margin), resize observer, three-line visual clamp (shortened from six at the final review request), and Read More / Read Less controls. Both observers disconnect on cleanup. Missing observers fall back to loading on mount and measuring on window resize.
- The component renders the complete server-sanitized HTML; no HTML strings are sliced or reconstructed. Only measured overflow exposes the toggle. A one-em fade softens the clipped edge so paragraph spacing cannot leave a hard cut through glyphs; links entering the fade also leave the tab order. Clipped anchors temporarily leave the keyboard tab order and regain it on expansion, using local rectangle checks without changing the document structure.
- Each card reuses its existing detail request/result for the inline body and Comments dialog, deduplicates pending loads, ignores stale responses, and retains the excerpt with feedback/retry on failure. Comments, likes, reports, and management controls keep their existing behavior.
- Logout lives only in Settings. `nav-logout` identifies the menu item and `settings-logout` its label; the same confirmation and current/all-device session workflow remain.

### Intentional test updates

The requested UX supersedes three former expectations: desktop cards side by side, Read More opening a dialog, and Logout being directly visible in navigation. Existing tests now check stacked cards, use Comments for dialog checks, and open Settings for logout. Logged-in state checks use the existing profile control. Focus/disabled assertions target the Settings menu item. No existing test cases were deleted or skipped; the behavior checks remain.

The shared mocked shell now supplies detail responses for every mocked post ID, because visible cards load bodies before opening Comments. The visual spec adds expanded-feed and body-error captures, and waits for lazy bodies before full-page screenshots so capture height stays stable. `feed_polish.cy.js` adds 15 focused cases for inline behavior, request handling, observer fallbacks, keyboard access, responsive feeds, compact suggestions, settings-only logout, and actual server-sanitized rendering.

Development caught and fixed React replacing the local clipped-link tab-order adjustment during rerender; keeping the HTML render prop stable preserves it. A subsequent new-test assertion-chain error was corrected without changing its checks. The single full regression passed **94/94 tests across 21 specs in 5m 21s**: **79 existing tests (including the original 45), 15 added tests, 0 failures, 0 pending, 0 skipped**. The selected existing development specs passed 59/59; the corrected new spec passed 15/15.

The user requested a shorter preview while the full regression was running. That run tested the six-line version; the final implementation uses three lines. The two resize/fallback fixtures were shortened to continue exercising content that fits on desktop but overflows on mobile, and a proportional assertion verifies the three-line limit. Frontend lint and the production build passed after the final three-line clamp and fade changes. The final targeted run passed **25/25 tests in 5m 58s** (15 feed, 4 responsive, 6 visual), with **0 failures, 0 pending, 0 skipped**. No second full suite was run. The final source inventory remains **94 tests in 21 specs**, with no exclusive tests.

Manual visual review completed for **114 browser captures across 19 screens/states**, at **375px, 768px, and 1280px in both light and dark themes**. Reviewed collapsed/expanded feeds, body loading errors, TopBar/Settings/logout, sidebar, human and agent profiles, Comments, editors, auth/reset, admin, long content, and empty/error states. Existing contrast and overflow checks retain their thresholds. Native keyboard activation, clipped-link tab order, focus retention, and dialog focus return passed; no separate accessibility runner exists. The local clipped-link handling covers wrapped links without DOM reconstruction; no additional keyboard refactor was needed.

Logs: `cypress/logs/feed-focused.log`, `cypress/logs/feed-targeted.log`, `cypress/logs/feed-focused-retry.log`, `cypress/logs/feed-full.log`, `cypress/logs/feed-final-preview.log`, and `cypress/logs/feed-final-checks.log`.

## Final mobile polish (2026-10-11)

Baseline: **94 Cypress tests across 21 specs**, at `fbbb38c`.

- Home puts the feed before Trending / Who to Follow below the existing 1200px sidebar breakpoint. The DOM order now matches the mobile reading/tab order; desktop retains its existing right-hand sticky sidebar and column widths. Loading, empty, error, and retry feedback stay before discovery.
- The same pulse SVG now lives in `src/assets/pulsenet-mark.svg`, has explicit 32px intrinsic dimensions, and is imported through Vite by the TopBar and favicon. The production build emits one fingerprinted SVG URL for both, rather than relying on the root `/favicon.svg` path. The local production response is HTTP 200 with `image/svg+xml`, and image decoding works on nested routes and reload.
- Replaced the fixed-height crop and fade with a native three-line clamp. Local measurement uses the actual clamped height and overflow, so paragraph spacing, line breaks, headings, and lists end on complete text rows. The HTML remains intact, Read More / Read Less stays inline, and the existing local observers, request reuse, clipped-link keyboard behavior, and focus handling remain.
- Mobile rich-text h1/h2/h3 sizes are bounded at 1.4rem / 1.2rem / 1.05rem below 600px, including Comments. Desktop heading typography is unchanged.
- Who to Follow retains three suggestions and all follow/replacement behavior. Only phone padding, row gaps, and avatar size are slightly reduced; buttons retain their existing size.

Intentional existing-test updates: the two sidebar placement checks now expect discovery below the mobile feed; the previous fixed-height preview assertion now checks three-line clamping, supported by new rendered-text geometry assertions. No existing test cases or behavior checks were removed. The seven new cases in `mobile_polish.cy.js` cover reading/DOM order, both themes with six rich-text samples and complete-line checks, heading bounds, logo/favicon production delivery, and loading/empty/error/retry order.

Targeted development checks: all **19 existing affected tests passed** (4 responsive, 15 feed). The initial new-spec run passed 5/7; two assertions used an unprefixed CSS mask property unavailable in Cypress's bundled Electron 118. The test now checks either supported property without relaxing the expected absence of a mask. The focused rerun passed **7/7**, with 0 failures, pending, or skips. Final frontend lint and production build passed.

Additional production-browser verification used already-installed WebKit and Chromium, without adding dependencies. All **12 browser/theme/viewport combinations** passed at **375/768/1280px × light/dark**: SVG decode and matching favicon, complete three-line previews for paragraphs/headings/lists/code blocks, inline expansion/collapse, sidebar placement, and no horizontal overflow. **48 final browser captures** were manually reviewed. This is local WebKit verification, not a physical iPhone test. The previously reported broken image did not reproduce in the old local WebKit build, so its device-specific root cause is unconfirmed; the new bundled path, explicit dimensions, and production decoding are verified.

The single full regression passed **101/101 tests across 22 specs in 4m 01s**: **94 existing tests passed (including the original 45), 7 new tests passed, 0 failures, 0 pending, 0 skipped**. Existing auth, Settings/theme, keyboard, accessibility-related visual checks, comments, and interaction coverage passed. No tests were removed, skipped, or made exclusive.

An additional production-browser code-block check found a Chromium edge case while the full run was in progress: a scrolling `pre` creates an independent formatting context and can escape the clamp. The final local fix lets code lines participate in the collapsed preview and removes its bottom padding so a fourth row cannot leak through; expanding restores normal code-block scrolling/padding. Measurement temporarily applies the collapsed attributes and restores them before painting, without reconstructing HTML. The new rich-text cases now include multiline code. The full run above predates this last edge-case fix; only affected checks are rerun afterward, preserving the one-full-run limit. The final source passed **26/26 affected Cypress tests in 29s** (7 mobile, 4 responsive, 15 feed), with **0 failures, 0 pending, 0 skipped**. Final lint/build and all 12 WebKit/Chromium viewport/theme combinations also passed after that fix. The existing bundle-size warning remains a deferred follow-up.

Logs: `cypress/logs/mobile-targeted.log`, `cypress/logs/mobile-focused-retry.log`, `cypress/logs/mobile-full.log`, `cypress/logs/mobile-final-targeted.log`, `cypress/logs/mobile-code-final.log`, and `cypress/logs/mobile-verified.log`. Temporary browser captures are under `%TEMP%/pulsenet-mobile-review/`. No backend, API, deployment, dependency, route, auth, Settings, or testid changes.

## Post-submission follow-ups

- Defer popular/most-traffic posts: existing paginated data has likes/comments but no traffic metric or complete ranking. Do not present a partial-page sort as a site-wide popularity feature.
- Separate post-preview/detail/management responsibilities in SinglePost only with dedicated regression coverage.
- Revisit SearchBar naming/responsibilities and comments organization as a deliberate refactor.
- Consider route/editor code splitting for the existing large-bundle warning (feed-pass entry about 883 KB minified / 270 KB gzip).
- Broaden automated accessibility checks beyond the focused keyboard, naming, contrast, and overflow checks included here.

No merge or push to main is part of this pass. Concurrent edits in the main checkout are outside this branch and have been left untouched.
