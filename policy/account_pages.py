"""The Account, Forgot password, and Reset password pages' data addresses (S044.2).

``/parent/api/account`` reads the signed-in account, and
``/parent/api/account/password`` changes its own password. Both are open to
reviewers: changing your own password is a reviewer write listed in Access
control in docs/parent-portal.md.

``/parent/api/password-reset`` says whether resetting by email is on, and a
POST to it sends a reset link. ``/parent/api/password-reset/save`` sets a new
password with a link's token. Both work with no session. Neither answer says
anything about an account or a token: the answer, and the work done before
it, are the same whether or not an email goes out or the token is valid. Each
email is sent after the answer, on a worker thread, so its time does not show
in the answer's.

The household's password rules (S046) are checked on both pages, with the
same hashing work for every request in ``screen_password``. Once the
passwords are sent, the Account page's answer is the same for a wrong
current password and for a new password a rule refuses, and the Reset
password page's answer is the same for a saved password, a link that is not
valid, and a password a rule refuses. Each refusal for an account is a line
in the service log, with the reasons and never the password. The rule
settings go out with ``/parent/api/account`` and ``/parent/api/password-reset``,
which the Account, Reset password, and Password help pages load.

A reset link names the host the Forgot password page was opened with when it
is one of ``PARENT_NAMES``, otherwise the first of them, so a forged Host
header cannot send a token anywhere else. The port is always ``POLICY_PORT``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

import secrets

from policy.accounts import Accounts, new_password_problem, screen_password
from policy.password_rules import known_words
from policy.mail import CHANGED_ON_PAGE, RESET_BY_EMAIL, MailError, Mailer, moment, portal_address, span
from policy.portal import CLOSED, PortalGate, json_answer, json_body, session_key

# Each body holds at most a username or three passwords of at most 200 characters, and a token.
LONGEST_BODY = 4096
NOT_SET_UP = "Resetting a password by email is not set up. Ask whoever runs Daywarden."
HELP = "/parent/password-help"
# The answer to a wrong current password and to a new password a rule refuses, alike.
NOT_CHANGED = {"error": "Your password was not changed. Learn more", "link": "Learn more", "help": f"{HELP}#account"}
# The answer to every Save on the Reset password page.
SAVED = {
    "message": "Try signing in with your new password. If it does not work, learn more",
    "link": "learn more",
    "help": f"{HELP}#reset",
}


def stand_ins() -> list[str]:
    """Known words for a reset link that is not valid, the size of a username and an address, so zxcvbn does as much."""
    name = secrets.token_hex(3)
    return [name, f"{name}@example.net", name]


def link_host(request: Request, names: tuple[str, ...]) -> str:
    """Return the name the request was sent to when it is one of names, otherwise the first of them."""
    asked = urlsplit("//" + request.headers.get("host", "")).hostname or ""
    for name in names:
        if name.lower() == asked.lower():
            return name
    return names[0]


def sent_answer(lifetime: timedelta) -> str:
    return f"If that account has an email address, a link to reset its password is on its way. It works for {span(lifetime)}."


def install_account_pages(
    app: FastAPI,
    *,
    gate: PortalGate,
    accounts: Accounts,
    loaded: Callable[[], object],
    mailer: Mailer | None,
    reset_lifetime: timedelta,
    names: tuple[str, ...],
    port: Callable[[], int],
) -> None:
    """Add the Account, Forgot password, and Reset password data addresses to app, before the portal's catch-all."""

    def household(at: datetime | None = None) -> str:
        return moment(loaded().clock.local(at))

    def notice(to: str | None, username: str, how: str) -> BackgroundTask | None:
        """The notice that a password changed, sent after the answer on a worker thread. None when there is no address."""
        if mailer is None or to is None:
            return None
        when = household()

        def send() -> None:
            try:
                mailer.changed(to, username, how, when)
            except MailError as error:
                print(f"the password-changed email for {username} was not sent: {error}", flush=True)

        return BackgroundTask(send)

    async def opened(request: Request) -> Response | None:
        """The refusal for a page that needs no session: plain HTTP, or no parent account."""
        if request.url.scheme != "https":
            return json_answer(403, {"error": "Open this page over HTTPS."})
        if accounts.count() == 0:
            return json_answer(403, {"error": CLOSED, "closed": True})
        return None

    @app.get("/parent/api/account")
    async def account(request: Request) -> Response:
        parent, refused = gate.parent(request)
        if refused is not None or parent is None:
            return refused
        found = accounts.entry(parent.username)
        return json_answer(
            200,
            {
                "username": parent.username,
                "role": parent.role,
                "email": None if found is None else found.email,
                "rules": accounts.rules.public(),
            },
        )

    @app.post("/parent/api/account/password")
    async def change_password(request: Request) -> Response:
        if request.url.scheme != "https":
            return json_answer(403, {"error": "Open this page over HTTPS."})
        body, refused = await json_body(request, LONGEST_BODY)
        if refused is not None:
            return refused
        parent, refused = gate.parent(request)
        if refused is not None or parent is None:
            return refused
        current, new = body.get("current"), body.get("password")
        problem = new_password_problem(new, body.get("again"))
        if problem is not None:
            return json_answer(400, {"error": f"{problem} Nothing was changed."})
        assert isinstance(new, str)
        account_id, stored, email, history = accounts.change_facts(parent.username)
        # The current password is checked as a sign-in checks it, and every rule is checked even when it is wrong.
        screened = await run_in_threadpool(
            screen_password,
            accounts.rules,
            new,
            history=history,
            known=known_words(parent.username, email, current),
            current=current,
            stored=stored,
        )
        reasons = ([] if screened.current_ok else ["current password wrong"]) + [found.reason for found in screened.broken]
        if account_id is None or reasons:
            print(f"password for {parent.username} refused on the Account page: {', '.join(reasons)}", flush=True)
            return json_answer(400, NOT_CHANGED)
        accounts.apply_change(account_id, screened.digest, session_key(request))
        return json_answer(
            200,
            {"message": "Your password was changed."},
            background=notice(email, parent.username, CHANGED_ON_PAGE),
        )

    @app.get("/parent/api/password-reset")
    async def reset_on(request: Request) -> Response:
        refused = await opened(request)
        if refused is not None:
            return refused
        return json_answer(
            200, {"email": mailer is not None, "lifetime": span(reset_lifetime), "rules": accounts.rules.public()}
        )

    @app.post("/parent/api/password-reset")
    async def forgot(request: Request) -> Response:
        if request.url.scheme != "https":
            return json_answer(403, {"error": "Open this page over HTTPS."})
        body, refused = await json_body(request, LONGEST_BODY)
        if refused is not None:
            return refused
        refused = await opened(request)
        if refused is not None:
            return refused
        if mailer is None:
            return json_answer(404, {"error": NOT_SET_UP})
        username = body.get("username")
        host = link_host(request, names)
        now = loaded().clock.local()

        async def send() -> None:
            # After the answer, on the event loop, where the database connection lives.
            link, cooling = accounts.request_reset(username, now)
            if cooling:
                print(f"password reset for {username} skipped: a link was sent less than 5 minutes ago", flush=True)
            if link is None:
                return
            address = portal_address(host, port(), f"/parent/reset#{link.token}")
            ends = household(now + reset_lifetime)
            try:
                await run_in_threadpool(mailer.reset, link.email, link.username, address, ends)
            except MailError as error:
                print(f"the reset email for {link.username} was not sent: {error}", flush=True)

        # The same answer, at once, whatever happens next.
        return json_answer(200, {"message": sent_answer(reset_lifetime)}, background=BackgroundTask(send))

    @app.post("/parent/api/password-reset/save")
    async def reset_save(request: Request) -> Response:
        if request.url.scheme != "https":
            return json_answer(403, {"error": "Open this page over HTTPS."})
        body, refused = await json_body(request, LONGEST_BODY)
        if refused is not None:
            return refused
        refused = await opened(request)
        if refused is not None:
            return refused
        password = body.get("password")
        problem = new_password_problem(password, body.get("again"))
        if problem is not None:
            return json_answer(400, {"error": problem})
        assert isinstance(password, str)
        token = body.get("token")
        now = loaded().clock.local()

        async def save() -> None:
            # After the answer. The database parts run on the event loop, and the hashing on a worker thread.
            target = accounts.reset_target(token, now, reset_lifetime)
            # The work of a valid link, done for every link.
            screened = await run_in_threadpool(
                screen_password,
                accounts.rules,
                password,
                history=[] if target is None else target.history,
                known=stand_ins() if target is None else known_words(target.username, target.email),
            )
            if target is None:
                return
            if screened.broken:
                reasons = ", ".join(found.reason for found in screened.broken)
                print(f"password for {target.username} refused from a reset link: {reasons}", flush=True)
                return
            done = accounts.apply_reset(target, screened.digest)
            if done is not None and done.had_password:
                sending = notice(done.email, done.username, RESET_BY_EMAIL)
                if sending is not None:
                    await sending()

        return json_answer(200, SAVED, background=BackgroundTask(save))
