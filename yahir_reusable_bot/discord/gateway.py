"""The reusable Discord gateway: ``BotThread`` + ``build_client`` + summon orchestration (D-06).

The generic, domain-agnostic gateway plumbing relocated out of the app, cut along the
generic/app seam so the module names no app concept and imports zero app code:

- :class:`BotThread` — runs a :class:`discord.Client` on its OWN thread + event loop via
  ``asyncio.run(client.start(token))`` (NOT the blocking ``Client.run`` helper, which only
  works on the main thread). Health failures (invalid token, any crash) die inside the
  thread and NEVER take down the host's scheduler (failure isolation). ``stop`` schedules
  ``client.close()`` cross-thread onto the bot loop and joins.
- :func:`build_client` — the ``Intents.none()`` + three-intent setup, the ``on_ready``
  ``message_content`` startup assertion, and the persistent-view registration in
  ``setup_hook`` (which discord.py invokes ONCE per process, pre-connect — unlike
  ``on_ready``, which re-fires on every reconnect → duplicate registrations). The
  ``on_message`` handler and the persistent view are INJECTED by the caller (the app
  constructs its :class:`~yahir_reusable_bot.discord.panelkit.PanelKit` with its own
  ``render`` + cosmetics + marker and hands it in), so ``setup_hook`` calls
  ``client.add_view(view)`` with NO app import.
- :func:`summon_panel` — the generic create-before-delete summon orchestration: the pin
  scan, the no-zero-panel-window ordering (send + pin the fresh panel FIRST, then delete
  prior owned), the owned-panel predicate (marker-bound), and the per-write
  ``discord.Forbidden`` backstop. Everything app-specific (the channel resolution, the
  operator-feedback copy, the idle embed, the panel factory) is INJECTED by the caller.

The persistent-view ``custom_id`` routing contract is valid only against the exact
discord.py version the live panel was registered against — the adapter owns the exact
``discord.py==2.7.1`` pin (D-05).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Awaitable, Callable

import discord
import structlog

__all__ = [
    "BotThread",
    "build_client",
    "summon_panel",
    "REQUIRED_PANEL_PERMS",
]

_log = structlog.get_logger(__name__)

# The exact channel permissions a panel summon preflights BEFORE any write (A4 — names
# Discord permissions, not any app concept). ⚠️ ``pin_messages``, NOT ``manage_messages`` —
# Discord split PIN_MESSAGES out of MANAGE_MESSAGES (effective 2026-01-12) and discord.py 2.7
# exposes the new bit as ``Permissions.pin_messages``; checking ``manage_messages`` would
# falsely pass on a server that granted only the new "Pin Messages" permission.
REQUIRED_PANEL_PERMS: tuple[str, ...] = (
    "view_channel",
    "send_messages",
    "embed_links",
    "read_message_history",
    "pin_messages",
)

# Type aliases for the injected collaborators (kept generic — the module never inspects them).
OnMessage = Callable[[discord.Message], Awaitable[None]]
OwnedPredicate = Callable[[discord.Message], bool]
PanelFactory = Callable[[], discord.ui.View]


def build_client(
    *,
    on_message: OnMessage,
    view: discord.ui.View,
) -> discord.Client:
    """Construct the gateway :class:`discord.Client` with minimal intents + injected handlers.

    Intents: start from ``none()`` then enable only ``guilds``, ``guild_messages``, and
    ``message_content`` (the last is a privileged intent that must also be toggled on in the
    Discord developer portal). An ``on_ready`` startup assertion logs CRITICAL if
    ``message_content`` did not actually arrive (so a missing portal toggle is loud, not a
    silently dead bot).

    Persistent-view registration: ``setup_hook`` — which discord.py invokes ONCE per process,
    before the first gateway connect (unlike ``on_ready``, which re-fires on every reconnect)
    — registers the INJECTED ``view`` via ``client.add_view``. That re-binds the
    already-pinned panel's button/select callbacks purely by their static ``custom_id`` after
    a restart, with no boot-time scan. ``view`` is constructed by the caller (the app builds
    its panel with its own cosmetics injected) — so this function imports no app code.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True  # privileged

    client = discord.Client(intents=intents)

    @client.event
    async def setup_hook() -> None:
        # Runs ONCE per process pre-connect (NOT on_ready: on_ready re-fires on every gateway
        # reconnect → duplicate persistent-view registrations). add_view is a purely-local
        # call (no network/await) → safe before connect. The view is injected, so NO app
        # import is needed here (the deferred back-edge that used to live here is gone).
        client.add_view(view)

    @client.event
    async def on_ready() -> None:
        if not client.intents.message_content:
            _log.critical(
                "message_content intent missing — enable it in the Discord "
                "developer portal; the bot cannot read commands"
            )
        else:
            _log.info("inbound bot ready", user=str(client.user))

    @client.event
    async def on_message(message: discord.Message) -> None:
        await on_message(message)

    return client


async def summon_panel(
    *,
    channel: discord.abc.Messageable,
    bot_user: discord.abc.User,
    idle_embed: discord.Embed,
    panel_factory: PanelFactory,
    is_owned: OwnedPredicate,
    on_created: Callable[[], Awaitable[None]],
    on_resummoned: Callable[[], Awaitable[None]],
    on_strays_cleaned: Callable[[int], Awaitable[None]],
) -> None:
    """Create-before-delete summon orchestration — the no-zero-panel-window ordering (D-06).

    The GENERIC half of the app's ``!panel`` summon: scan the channel's pins for bot-owned
    panels (via the injected marker-bound ``is_owned`` predicate), post + pin a FRESH panel
    at the channel bottom FIRST (create-before-delete, so there is never a zero-panel window
    even if a later delete fails), then DELETE every prior owned panel + strays.

    Everything app-specific is INJECTED: the resolved ``channel`` + ``bot_user`` (the caller
    does the config read + channel resolution + permission preflight), the ``idle_embed``
    (built via the app's render), the ``panel_factory`` (constructs the app's panel with its
    cosmetics injected), and the operator-feedback callbacks (``on_created`` /
    ``on_resummoned`` / ``on_strays_cleaned`` — the caller owns the copy strings). Each write
    is guarded by an inner ``discord.Forbidden`` catch (the TOCTOU backstop): a permission
    revoked between the caller's preflight and a write is logged and swallowed, never bubbled.
    """
    try:
        # Scan owned panels FIRST. Async iterator — NOT ``await channel.pins()`` (deprecated
        # awaitable). Discord caps pins at 50, no pagination needed.
        matches = [m async for m in channel.pins() if is_owned(m)]
        # Create-before-delete (no-orphan ordering): post the fresh panel as the NEWEST
        # channel message (bottom) and pin it FIRST, so there is never a zero-panel window
        # even if a later delete fails.
        msg = await channel.send(embed=idle_embed, view=panel_factory())
        await msg.pin()
        # THEN DELETE every prior owned panel (the previously-pinned one + any strays).
        # Deleting the old pinned message also clears its pin, so net pins return to exactly
        # one. DELETE, never unpin-only — an unpinned-but-live View still responds to clicks.
        for old in matches:
            await old.delete()
        if not matches:
            await on_created()
        elif len(matches) > 1:
            # One prior panel is logically replaced by the fresh one; the rest were strays.
            await on_strays_cleaned(len(matches) - 1)
        else:
            await on_resummoned()
    except discord.Forbidden:
        # TOCTOU backstop: a permission was revoked between the preflight and a write. Log
        # CRITICAL and return — never let the 403 bubble out. ``channel_id`` is a non-secret
        # structured field; never leak the token.
        _log.critical(
            "panel summon write forbidden (403) despite preflight",
            channel_id=getattr(channel, "id", None),
        )
        return


class BotThread:
    """Run the gateway client on its OWN thread + event loop.

    Uses ``asyncio.run(client.start(token))`` (NOT the blocking ``Client.run`` helper, which
    only works on the main thread). Health failures (invalid token, any crash) die inside this
    thread and NEVER take down the host's scheduler (failure isolation). ``stop`` schedules
    ``client.close()`` cross-thread onto the bot loop via ``asyncio.run_coroutine_threadsafe``
    and then joins the thread.

    The client is INJECTED (built by :func:`build_client` with the caller's ``on_message`` +
    persistent view) so ``BotThread`` names no app concept and constructs nothing app-specific.
    """

    def __init__(self, token: str, *, client: discord.Client) -> None:
        self._token = token
        self._client = client
        self._loop: asyncio.AbstractEventLoop | None = None
        # ``_loop_started`` signals only that the thread reached ``_amain`` and the event loop
        # is up — it does NOT imply a successful gateway login. An invalid token raises
        # ``LoginFailure`` AFTER this is set; that failure surfaces later as a CRITICAL log in
        # ``_run`` and flips ``_failed``.
        self._loop_started = threading.Event()
        # Set in the ``_run`` except handlers when the thread dies. Lets the host make a
        # dead-start teardown explicit instead of inferring it from ``loop.is_running()``.
        # Failure isolation is preserved: ``_run`` never raises.
        self._failed = False
        self._thread = threading.Thread(
            target=self._run, name="discord-gateway", daemon=True
        )

    def start(self) -> None:
        """Start the bot thread and wait (up to 5s) for its event LOOP to come up.

        NOTE: a returned ``start()`` means only that the bot loop started — NOT that the
        gateway authenticated/connected. An invalid token logs CRITICAL and flips
        ``is_alive()`` to False asynchronously; callers must consult ``is_alive()`` (not the
        mere return of ``start()``) to know the bot is live.
        """
        self._thread.start()
        if not self._loop_started.wait(timeout=5.0):
            _log.warning("bot thread did not signal loop-started within 5s")

    def is_alive(self) -> bool:
        """True unless the bot thread has died in ``_run``.

        Returns False once a ``LoginFailure`` / unexpected crash has been caught in ``_run``
        (``_failed`` set) OR the underlying thread has exited. The host can use this to null
        out a confirmed-dead bot and skip a no-op ``stop()``.
        """
        return not self._failed and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the bot: schedule ``client.close()`` cross-thread, then join."""
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._client.close(), loop)
            try:
                future.result(timeout=timeout)
            except Exception:  # noqa: BLE001 — close best-effort; still join below
                _log.warning("bot client.close() did not complete cleanly")
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            _log.warning("bot thread did not stop within timeout")

    def _run(self) -> None:
        """Thread target: run the bot loop; isolate ALL failures here.

        On ANY failure the ``_failed`` flag is set so ``is_alive()`` reports a dead start,
        then the failure is SWALLOWED — it never propagates into the host thread (failure
        isolation).
        """
        try:
            asyncio.run(self._amain())
        except discord.LoginFailure:
            self._failed = True
            _log.critical(
                "invalid Discord token; inbound bot disabled, scheduler unaffected"
            )
        except Exception:  # noqa: BLE001 — die alone; never crash the process
            self._failed = True
            _log.critical("inbound bot thread crashed; scheduler unaffected")

    async def _amain(self) -> None:
        """Bot loop entrypoint: record the loop, signal loop-started, then start the client."""
        self._loop = asyncio.get_running_loop()
        self._loop_started.set()
        async with self._client:
            await self._client.start(self._token)  # NOT the blocking Client.run helper
