# Parent portal

The parent portal is the parent's side of Daywarden: one React Router app, served by the decisions service on the HTTPS parent port at `/parent/`. These rules are binding for every parent page. A change that breaks one of them changes this document in the same change, and the Parent Portal section of `AGENTS.md` too when its summary changes.

## Scope

- The portal is the parent side only. It holds the sign-in screen and every page a parent uses: the attempt review, the usage report, and later the editors and analytics.
- The child's task pages under `/tasks/...` and `/quiz` are not part of the portal. They keep their own simple layout with large fonts and large controls. The portal's components, stylesheets, palette, layout, and build never apply to them, and portal work does not change their layout or design.
- The one piece of code the portal and the child's pages share is `policy/static/word_sort.js`, the drag-and-drop that sorts words into a table, used by the parts of speech editor and the child's parts of speech page. It is plain JavaScript outside the portal. The portal imports it, with `word_sort.d.ts` beside it, and the child's page inlines it into its own script. It marks elements only with `data-` attributes, and each page styles those with its own palette, so a change to it is checked on both pages.

## Layout

Every signed-in page has the same frame:

- **Sidebar.** Down the left side for the full height of the window. The logo is centred at the top, then the page entries, then who is signed in and Sign out at the bottom. The entry for the open page is marked. Entries that do not fit scroll between the logo and the bottom cluster, and the logo and the bottom cluster stay in place. The sidebar may grow headed groups, such as Reports and Settings, when there are enough entries to need them.
- **Main pane.** The rest of the window, from top to bottom:
  - **Context bar.** One line high, across the full width of the main pane. It holds what the page is about and the choices for it: the page title or a breadcrumb such as Attempts › younger › spelling-week-3, the page's pull-downs, and buttons that act on what is on show, such as Record parent check.
  - **Content pane.** Takes most of the window and holds the page itself.
  - **Status bar.** One line high, across the full width of the main pane. It holds facts about what is on show, such as how many records are listed and the timezone of the times, and confirms or refuses the last action.

Scrolling:

- The browser window never scrolls. The sidebar, the context bar, and the status bar never scroll away. Only the content pane scrolls.
- A list of records keeps its column headers at the top of the content pane while its rows scroll beneath them, using `position: sticky` inside the content pane's scroll container. A page with several record lists, such as one table per day, keeps each list's headers in view while that list scrolls. A page with no column headers, such as a dashboard, scrolls as a whole.

Sidebar size:

- The parent resizes the sidebar by dragging its right edge, or by focusing that edge and using the arrow keys. It is never narrower than 12.5rem and never wider than a third of the window. When a third of the window is less than 12.5rem, it stays at 12.5rem. The width on screen is clamped on load and whenever the window is resized.
- The logo scales with the sidebar up to a maximum size.
- A chevron near the top collapses the sidebar to a thin strip that shows only the expand chevron and Sign out. The strip cannot be resized. Expanding brings back the width from before.
- Collapsing and expanding the sidebar animate, as every expand and collapse in the portal does. See Motion below.
- The chosen width and whether the sidebar is collapsed are kept in `localStorage`, so they last across page changes, reloads, and reopening the portal in the same browser. Collapsing keeps the stored width.

Sidebar groups:

- An entry that holds other entries, such as Task Administration, is a `<button>` with `aria-expanded`, because it expands and collapses its list rather than going anywhere. Each entry in its list is a real link, indented beneath it. The list expands and collapses with the shared animation.
- Whether a group is expanded is kept in `localStorage`, as the sidebar width is. A group is always expanded while one of its pages is open, with that page marked, and opening one of its pages keeps it expanded afterwards.
- The collapsed sidebar strip does not show a group's list.

The sign-in screen is the one page without the frame. It shows the logo, the username and password fields, and the Login and Reset buttons, grouped in the centre of the window.

The portal is laid out for a desktop browser window. A narrow-window layout is not part of it yet.

## Links and addresses

- Every navigation is a real link, an `<a href>` rendered by React Router's `<Link>` or `<NavLink>`. Open in a new tab, middle click, Ctrl-click, copy link address, and copying a link as rich text all work. A plain click changes the content pane without reloading the page.
- Every action, such as Sign out or Record parent check, is a `<button>` and looks like a button, not a link.
- Every page and every choice on it has its own URL. Choices, such as a client group or a usage view, live in the query string through the router's search parameters, never in component state. Back, Forward, Reload, a bookmark, and a URL sent to the other parent all open the same page and choice.
- Portal pages live under `/parent/`, and the router's base path is `/parent`. Data lives under `/parent/api/`. A data address is always told apart from a page address by its path. Built files live under `/parent/assets/`, with the favicon and icons at the top of `/parent/`.
- The service returns the portal's `index.html` for every `/parent/...` address that is not a built file and not under `/parent/api/`, so a deep link and Reload work. `index.html` is sent `no-store`. Hashed files under `/parent/assets/` may be cached for good. A missing file under `/parent/assets/` is a 404, not the portal page. An unknown address under `/parent/api/` is a JSON 404, never the portal page.
- An unknown portal page address shows a not-found message in the content pane, with the frame around it.
- A new page is a new route under the layout in `policy/portal/src/routes.tsx` and an entry in the sidebar in `policy/portal/src/components/Sidebar.tsx`.

## Editing pages

A page that edits something, such as a task page, follows these rules:

- Changes are made on screen first, and nothing is written until the parent saves. Save is a button at the right-hand end of the context bar. Ctrl+S anywhere on the page saves too, and never opens the browser's save dialog. One save sends every unsaved change on the page at once.
- Save is disabled while nothing has changed, and Ctrl+S then does nothing. While there are unsaved changes, an Unsaved changes marker sits beside Save in the context bar.
- A changed field or row is marked until it is saved. The status bar confirms a save, or refuses it and lists each reason, such as each error a policy check found.
- Fields are labelled in words, such as Pass Cooldown. Each label's title is the policy file's field name, such as `pass_cooldown`, which is what the errors name.
- Every editable field that holds a date is a `yyyy-mm-dd` text box with a calendar beside it, `DateField` in `src/components/DateField.tsx`. The calendar opens with its button or Alt+Down, marks the household's today in the policy's `timezone`, and opens and closes with the shared animation. Text that is not a real day is a problem under the box that blocks Save. The browser's own `<input type="date">` is not used.
- A choice of any number of options, such as a task's client groups, is a pull-down list. Closed, it shows the chosen options separated by commas. Open, the chosen options are highlighted, and one click, Space, or Enter turns an option on or off. It opens and closes with the shared animation.
- With unsaved changes, following a sidebar link, Back, and Forward ask whether to leave and lose the changes, in the portal's own dialog with Stay as the default. A choice that only changes the query string, such as a filter, keeps the changes and does not ask. Reload and closing the tab get the browser's own question.
- An action that cannot be taken back, such as Retire, asks first in the same dialog, with the choice that changes nothing as the default. An action that is done at once, as Retire is, is not part of the next save.
- A field that cannot be changed yet, such as every field of a new task before its name and type are locked in, or every field but the name while a task is renamed, is shown disabled. The fields that are disabled together sit in a `fieldset` with the `lock-area` class, which draws nothing itself.
- A save that needs a decision first, such as a warning that it does not ask a group to do a task again, asks in the same dialog before anything is written.
- A page that builds up work in progress on the service before a final step, such as the new week's spelling words before Apply, follows the same rules for the work in progress: Save or Ctrl+S keeps it, and leaving with unsaved changes asks. The final step, and anything that acts on what is saved, such as recording, is a separate button that is disabled while there are unsaved changes and says why in its title. After the final step, or throwing the work away, the page opens the page it belongs to, with the outcome in that page's status bar.

## Recording dialogs

A page that records from the microphone, such as the spelling word list, uses `RecordDialog` in `src/components/RecordDialog.tsx`. It is given the lines to say, and how to write the clips the parent keeps.

- The dialog asks for the microphone when it opens. A refusal, no microphone, or a recorder that will not start is said in the dialog, and nothing is recorded.
- Any key starts recording, except in a form field. The recorder starts `START_DELAY_MS`, 500ms, after the key, showing "Get ready…" meanwhile, so the clatter of the key is not recorded. During that pause every key is ignored. While recording, every key but Enter is ignored, and Enter stops. Escape closes the dialog only before anything is recorded. With a recording held, only Cancel closes it.
- The take is uploaded once, then cut with a JSON request. Cutting again with other Advanced settings reuses the take.
- The review keys, K, J, D, M, R, and B, work only during review, and never while the focus is in the Advanced section.
- The review shows the line expected and how far through the lines and clips it is, such as `3 of 18: rope (sentence). Clip 4 of 20.`, with the line's own text, such as a typed sentence, beneath it.
- Requests from the dialog use `api()` with `signedOut: "refuse"`, so an ended session keeps the take and the review in the page and asks the parent to sign in again in another tab. Nothing is sent again until the parent presses the button again.
- The Advanced section expands and collapses with the shared animation. Each field puts itself back to its `bin/cut-clips` default with its reset button, a double-click on its slider, or Alt+R, and Alt+Shift+R or Reset all puts back every field.

## Sessions and data

The portal uses the parent session from S007.1: a `Secure`, `HttpOnly`, `SameSite=Lax` cookie, an idle limit, and a lifetime.

- **The shell carries no household data.** `index.html`, the scripts, the stylesheets, and the images are the same for everyone and are served without a session. Attempts, usage, tasks, the household's group names, and the signed-in username come only from JSON endpoints under `/parent/api/`. Spelling recordings the task pages play also come from under `/parent/api/`, and need a session in the same way.
- **Data endpoints answer 401 or 403 and never redirect.** With no valid session they answer 401 with no data. With no parent account they answer 403 with `"closed": true` and no data. Over plain HTTP they are refused, as every parent address is. The browser does not follow these answers anywhere. Only the portal's own code reacts to them.
- **State-changing requests are JSON POSTs.** Sign-in, sign-out, the parent check, a task save, locking in a new task's name and type, creating a task, renaming one, Retire, cutting, keeping, or discarding a recording, and saving, applying, or cancelling a new week's words are `POST`s whose body must be `application/json`. Anything else is refused with 415, so a form on another site cannot act with the parent's cookie. A password in a query string is never read.
- **The one exception is a recording's upload.** `POST /parent/api/recordings` takes the raw audio, and only when its `Content-Type` is `audio/webm` or `audio/ogg`, with or without a `codecs` parameter. Anything else, including `multipart/form-data`, `application/x-www-form-urlencoded`, and `text/plain`, is refused with 415. A form on another site can send only those three refused types, a script on another site that sends an audio type needs a CORS preflight that the service never approves, and the `SameSite=Lax` cookie is not sent on a cross-site POST. A body over 20 MB is refused with 413 before it is read to the end. No other endpoint takes anything but JSON.
- **Sign-out ends the session on the service.** It deletes that session's row, so the key cannot be used again in any tab.
- **The portal makes no background requests.** A request happens only when the parent acts: opening a page, changing a choice, or pressing a button. There is no polling or timed refresh, so a tab left open does not extend the idle limit.

### Sign-in always returns to a portal page

After sign-in, the parent always lands on a portal page with the full frame. They never land on a data address, a file, or another site.

- The portal decides the return address. It never uses the address of the request that failed. Every data request goes through the one fetch helper, `api()` in `policy/portal/src/api.ts`, and each request names the page it belongs to:
  - A request made by a React Router loader belongs to the page being opened. The loader's `request.url` is that page's URL, not the data endpoint's. A 401 throws a redirect to `/parent/login?next=<that page>`.
  - A request made by an action, such as Record parent check, belongs to the page on show, with its query string. The action's `request.url` is that page.
  - A request that belongs to no page sends no `next`, so sign-in opens the portal home.
- The service checks `next` again before it answers a sign-in. A return address is used only when it is a path under `/parent/`, not under `/parent/api/` or `/parent/assets/`, not the sign-in screen itself, and its last segment is not a file name. A scheme, a host, a `..`, or anything else returns the portal home. The portal applies the same check to what the service answers.
- Sign-in only navigates. It never replays a refused request. An action is done again only when the parent presses its button again, so a sign-in never repeats a write such as a parent check.
- A later data address that is not under `/parent/api/`, such as React Router framework mode's `.data` requests, is added to the excluded paths in both checks. Data addresses must always be told apart from page addresses by their path.

## Styling and themes

- **Layout and theme are separate stylesheets.** `src/styles/layout.css` holds structure, sizes, spacing, and type, and names no colours. `src/styles/theme.css` holds every colour. No CSS framework or CSS-in-JS that compiles colours into class names or component code is used.
- **Palette properties feed role properties.** Palette properties, such as `--palette-navy`, name the theme's raw colours and are used only inside the theme stylesheet. Role properties say what a colour is for, such as `--sidebar-bg`, `--bar-bg`, `--content-bg`, `--content-text`, `--border`, `--row-hover`, `--focus-ring`, `--button-bg`, and `--button-text`. Layout CSS and components use only role properties. A colour a page needs is a new role property in the theme.
- **No colour values outside the theme.** No component, layout stylesheet, inline style, or TypeScript file names a colour, hex or otherwise. Lucide icons draw with `currentColor`, so they follow the text around them. Later charts read their series colours from role properties.
- **Beyond colours.** The theme also sets anything else a theme might change: `color-scheme` for the browser's scroll bars and form controls, shadows, and the logo images through `--sidebar-logo` and `--signin-logo`. Components never name an image path for the logo.
- **Themes are ready to add.** The theme's properties are defined on `:root` and on `:root[data-theme="daywarden"]`, and `index.html` sets `data-theme="daywarden"`. A later theme is a second stylesheet with its own `data-theme` value. Switching themes changes that attribute or the stylesheet, and no component changes. Nothing offers a theme choice yet.
- **Contrast.** Body text meets WCAG AA, 4.5:1. The current palette is midnight navy `#17243A`, antique gold `#D4B477`, soft teal `#80B9C5`, warm ivory `#E9E2D2`, and muted lavender `#777E9C`. Gold on navy is about 7.8:1, navy on teal about 7.2:1, and navy on ivory about 12:1. These are the sidebar, the context and status bars, and the content pane. Navy on lavender is only about 3.9:1, so lavender is used for borders, hover, and selected-row tints, never as a background behind text. Whether the content pane is ivory or white is a one-line change to `--content-bg` in the theme.

## Motion

- Every expand and collapse animates the same way: over `--expand-duration`, 500ms, with `--expand-easing`, the curve of jQuery's swing easing (`cubic-bezier(0.37, 0, 0.63, 1)`). Both properties are set once in `src/styles/layout.css`. Nothing else names an expand time or curve, and a new panel, section, or menu that opens and closes uses these two.
- Code that waits for an animation reads the duration with `expandDuration()` in `src/motion.ts`, so it never waits longer or shorter than the CSS runs. `useExpander()` there keeps collapsing content on screen while it animates out, makes it inert so the keyboard skips it, and removes it when the animation ends.
- When the browser asks for reduced motion, `--expand-duration` is `0ms` and every expand and collapse happens at once.
- Only an expand or a collapse animates. A drag, a key press on the resize handle, and a window resize change the sidebar width at once.

## Icons and controls

- Icons come from [Lucide](https://lucide.dev/) through `lucide-react`, which bundles them into the build. Another icon source is used only when Lucide has nothing suitable, and the change says why.
- A button with only an icon has an `aria-label` and a `title`, such as "Collapse sidebar", "Expand sidebar", and "Sign out".
- Every control works from the keyboard. Buttons are reached with Tab and work with Enter and Space. The sidebar's resize handle is a focusable separator that the left and right arrow keys move.
- Anything that can be dragged on a parent page has a keyboard way to do the same thing, such as the menu Enter opens on a word in the parts of speech editor.
- A page's own keys use Alt with a letter, as Alt+N adds a sentence and Alt+R resets a field in the recording dialog. Browsers keep Ctrl+N, Ctrl+T, and Ctrl+W for themselves, and Chrome never passes Ctrl+N to the page. Ctrl+S is the one Ctrl key the portal takes, for Save.

## Self-contained

The portal loads no fonts, scripts, images, or icons from outside the parent port. It uses the system font stack and bundles everything else into its build, so it works on a household network with no internet. The large logo originals in the repository root are not served. The portal uses a web-sized copy, and its favicon is cut from the owl.

## Build

- The portal source is `policy/portal/`: React, React Router in data mode, TypeScript, and Vite. Every package version in `package.json` is pinned exactly, and `package-lock.json` is committed.
- The decisions image is built in two stages. A Node stage runs `npm ci` and `npm run build`, with `policy/static/word_sort.js` copied in beside the portal as it sits in the repository, and the Python stage copies in only `policy/portal/dist`. `npm run dev` is allowed to serve that one directory outside the portal. The image and the `make dist` package need no Node at run time, and the target machine never builds an image. The `lib/policy/` copy that `make dist` makes for `cut-clips` leaves the portal out.
- `node_modules/` and `policy/portal/dist/` are not committed.
- The portal's tests use Vitest and React Testing Library in jsdom. `make test` installs the npm packages when Node is there, then runs those tests and the type check with the Python tests. Without Node they are skipped. The visual layout, the colours, the sticky headers, and the scrolling are checked in a browser, not in jsdom.
- `npm run dev` in `policy/portal` serves the portal from Vite with its data requests sent to the HTTPS parent port of a running stack.
