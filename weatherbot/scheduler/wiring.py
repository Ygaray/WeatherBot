"""The single app-side composition root: ``build_runtime`` (APP-01 / APP-02, D-04).

This is WeatherBot's ONE greppable wiring site (APP-01). It lifts ``run_daemon``'s
~200-line constructor/wiring block into a single delegated function that constructs
the holder + ``SchedulerEngine`` + ``ReloadEngine`` + the reusable ``ReadyGate`` +
the channel + the FOUR injected leak points, and returns the wired parts. This is a
MOVE, not a redesign (D-04 option d): ``run_daemon`` KEEPS the load-bearing
lifecycle ORDERING (SIGTERM-handler-before-gate, single-channel-build-once, PID
write before the gate, observer armed in ``finally``, gate -> ``scheduler.start()``
-> READY). ``build_runtime`` constructs; ``run_daemon`` sequences.

The reusable engines (``ReadyGate`` / ``ReloadEngine`` / ``SchedulerEngine``) live
in ``yahir_reusable_bot`` and name no weather concept; every WeatherBot specific
arrives here as an injected closure at the single site:

- leak point 3 (health-check): the ``health_check`` closure calls the app-side
  ``run_self_check`` and adapts its ``CheckResult`` to the module's neutral
  ``HealthResult`` via ``to_health_result`` — the module never sees a weather reason.
- leak point 2 (config id-deriver / exactly-once key): the ReloadEngine
  ``desired_jobs`` closure derives the WeatherBot job-id set; the module subtracts an
  app-supplied ``excluded_ids`` frozenset without naming any id.
- leak points 1 + 4 (selected-location context + ``render_embed`` panel cosmetics):
  threaded into the channel/bot the app constructs; the module owns no render.

Durable side-effects ride injected best-effort hooks (D-02a): the module owns ZERO
durable I/O. ``on_fail`` stamps the durable health row per failing probe (and logs
the app's classified CRITICAL/WARNING line); ``on_online`` starts the scheduler,
stamps the online row + heartbeat tick, logs the structured online event, and posts
the one-time Discord ping — all app-side, at today's EXACT call order. The module's
``ReadyGate`` owns ONLY ``notifier.ready()`` (READY=1), emitted STRICTLY AFTER
``on_online`` runs ``scheduler.start()`` — so READY never reaches systemd before the
scheduler is up (the most golden-sensitive invariant). ``build_runtime`` itself NEVER
emits READY.

Swappable collaborators (``BackgroundScheduler`` / ``run_self_check`` /
``SystemdNotifier`` / the ``_register_*`` / ``_announce_*`` / ``_run_catchup``
helpers / the ``stamp_*`` store fns) are resolved through the ``daemon`` module
object at call time, so the daemon-suite monkeypatches (``daemon_mod.X``) keep
biting the constructed parts byte-identically.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apscheduler.triggers.interval import IntervalTrigger

from weatherbot.config.loader import validate_config_and_templates
from weatherbot.ops import to_health_result
from weatherbot.ops.pidfile import PID_FILE, WEATHERBOT_PROC_MARKER
from yahir_reusable_bot.config import ConfigHolder, ReloadEngine
from yahir_reusable_bot.lifecycle import LifecycleIdentity, ReadyGate
from yahir_reusable_bot.scheduler import SchedulerEngine

if TYPE_CHECKING:
    from weatherbot.channels.base import Channel
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings


def default_identity() -> LifecycleIdentity:
    """The default WeatherBot ``LifecycleIdentity`` — byte-identical to today's paths.

    Reproduces the pre-25-02 process identity EXACTLY: PID file
    ``/run/weatherbot/weatherbot.pid`` (``PID_FILE``), the ``b"weatherbot"`` ``/proc``
    staleness marker (``WEATHERBOT_PROC_MARKER``), and the ``weatherbot`` runtime dir /
    console name. Constructed app-side and threaded into the lifecycle layer (D-03);
    a different bot supplies its own instance.
    """
    return LifecycleIdentity(
        name="weatherbot",
        pid_file=PID_FILE,
        runtime_dir=PID_FILE.parent,
        console_name="weatherbot",
        proc_marker=WEATHERBOT_PROC_MARKER,
    )


@dataclass
class RuntimeParts:
    """The wired parts ``build_runtime`` returns for ``run_daemon`` to sequence.

    ``run_daemon`` keeps the load-bearing lifecycle ORDERING using these — it does
    NOT re-construct anything. ``bot`` is always ``None`` here (the inbound BotThread
    is started by ``run_daemon`` strictly after the online signal, D-11) but is part
    of the contract so the caller's ``finally`` can reference it uniformly.
    """

    scheduler: Any
    stop: threading.Event
    holder: ConfigHolder
    cache: Any
    channel: Any
    bot: Any
    reload_engine: ReloadEngine
    ready_gate: ReadyGate
    notifier: Any
    identity: LifecycleIdentity
    started_at: Any
    watch: bool
    config_path: str | Path | None


def build_runtime(
    config: Config,
    settings: Settings | None,
    db_path,
    *,
    config_path: str | Path | None = None,
    client=None,
    channel: Channel | None = None,
) -> RuntimeParts:
    """Construct + wire every runtime collaborator at the single composition root.

    Lifts the constructor/wiring block out of ``run_daemon`` (D-04 MOVE): builds the
    channel-once, the scheduler + stop + holder + cache, registers the jobs +
    heartbeat + uv-monitor, announces the schedule, runs the catch-up scan, constructs
    the ``ReloadEngine`` (with the WeatherBot specifics injected as closures) and the
    new ``ReadyGate`` (with the injected ``health_check`` + ``on_fail`` + ``on_online``
    hooks + the default ``LifecycleIdentity``), and returns the wired parts.

    Does NOT install signal handlers, write the PID file, arm the observer, start the
    scheduler, drive the gate, or emit READY — those order-sensitive lifecycle steps
    stay in ``run_daemon`` (the load-bearing ordering, Pitfall 2 / D-04). READY is
    NEVER emitted from here.
    """
    # Resolve swappable collaborators through the daemon module object at CALL time so
    # the daemon-suite monkeypatches (daemon_mod.BackgroundScheduler / run_self_check /
    # SystemdNotifier / _register_* / stamp_* / threading.Event) bite the parts we
    # construct here byte-identically. Imported lazily to avoid a wiring<->daemon
    # import cycle (run_daemon imports build_runtime).
    import weatherbot.scheduler.daemon as daemon

    # Channel-from-settings fallback, build ONCE (daemon L1387-1393): the same single
    # instance threads into _register_jobs and the online ping. An injected channel
    # wins; an UN-GUARDED build_channel ValueError propagates BEFORE the gate so a
    # misconfigured channel fails loud at startup (fail-loud-at-load posture).
    if channel is None and settings is not None:
        from weatherbot.channels import build_channel

        channel = build_channel(config, settings)

    # Process start time (UTC) for the `status` uptime read (A5), captured up front.
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc)

    scheduler = daemon.BackgroundScheduler()
    # The shared shutdown Event (daemon L1406): threaded into every fire_slot job as
    # the retry's interruptible sleep source AND the gate's re-probe wait.
    stop = daemon.threading.Event()
    holder = ConfigHolder(config)

    # The per-location TTL ForecastCache the inbound bot reads (only when settings is
    # present). Lazy import keeps discord.py off the import-time graph (daemon L1424).
    bot = None
    cache = None
    if settings is not None:
        from weatherbot.interactive import ForecastCache

        cache = ForecastCache(settings=settings)

    daemon._register_jobs(
        scheduler,
        holder,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
        stop_event=stop,
    )
    # The periodic heartbeat tick on its own IntervalTrigger job (RELY-05, D-06).
    # Heartbeat-handle Option (d) (25-01): the ReadyGate holds NO scheduler handle;
    # the app re-registers __heartbeat__ here via the existing SchedulerEngine one-liner
    # so run_daemon's heartbeat wiring stays byte-identical.
    SchedulerEngine(scheduler).register(
        "__heartbeat__",
        IntervalTrigger(seconds=daemon.HEARTBEAT_INTERVAL_S),
        daemon._heartbeat_tick,
        kwargs={"db_path": db_path},
    )
    # The proactive UV monitor on its own IntervalTrigger job (UV-04), gated inside
    # the helper on uv.monitor_enabled, reusing the same holder/channel/client.
    daemon._register_uvmonitor_job(
        scheduler,
        holder,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
    )
    daemon._announce_schedule(scheduler, holder)
    daemon._run_catchup(
        holder,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
        stop_event=stop,
    )

    # RELOAD ENGINE (Phase 24): every WeatherBot specific injected as a closure
    # (daemon L1504-1561, lifted verbatim). _on_applied closes over reload_engine
    # (assigned just below — late binding; it is only called from the main poll loop).
    def _on_applied(summary: str) -> None:
        # COMMITTED-SUCCESS side effects, SAME order + EXACT strings as the in-place
        # path: post the outcome, invalidate the bot's ForecastCache, re-derive the
        # watch set. Each best-effort so a side-effect hiccup never aborts the reload.
        if channel is not None:
            try:
                channel.send(f"✅ config reloaded: {summary}")
            except Exception:  # noqa: BLE001 — best-effort post; reload already succeeded
                daemon._log.warning("reload-applied post failed; reload unaffected")
        if cache is not None:
            try:
                cache.invalidate()
            except Exception:  # noqa: BLE001 — best-effort; reload already committed
                daemon._log.warning(
                    "forecast cache invalidate failed; reload unaffected"
                )
        if config_path is not None:
            reload_engine.update_watch_dirs(
                daemon._derive_watch_dirs(holder.current(), Path(config_path))
            )

    reload_engine: ReloadEngine[Config] = ReloadEngine(
        holder,
        SchedulerEngine(scheduler),
        validate=lambda p: validate_config_and_templates(p),
        desired_jobs=lambda cfg: daemon._desired_job_ids(ConfigHolder(cfg)),
        register_jobs=lambda cfg: daemon._register_jobs(
            scheduler,
            ConfigHolder(cfg),
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            stop_event=stop,
            replace_existing=True,
        ),
        restore=lambda old: daemon._restore_jobs(
            scheduler,
            old,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            stop_event=stop,
        ),
        excluded_ids=frozenset({"__heartbeat__", "__uvmonitor__"}),
        on_rejected=(
            (lambda exc: channel.send(f"⛔ config reload rejected: {exc}"))
            if channel is not None
            else None
        ),
        on_applied=_on_applied,
    )

    notifier = daemon.SystemdNotifier()
    identity = default_identity()

    # ----- The READY-gate, wired with the four injected hooks (D-02 / D-02a) ----- #
    # leak point 3: the injected health probe. The closure calls the app-side
    # run_self_check (resolved on the daemon module so its monkeypatch bites) and
    # adapts the CheckResult to the module's neutral HealthResult — the module never
    # sees a weather reason, only ok + the neutral severity rung.
    def _health_check():
        result = daemon.run_self_check(config=config, settings=settings)
        return to_health_result(result)

    # on_fail (D-02a): the per-outcome durable health row stays app-side, PLUS the
    # app's classified CRITICAL/WARNING per-attempt log (preserving today's
    # daemon-logger split that the daemon-suite asserts on). The module's ReadyGate
    # ALSO logs a generic severity line to its own logger — additive, harmless, on the
    # failure path only.
    def _on_fail(result) -> None:
        daemon.stamp_health(db_path, reason=result.reason, detail=result.detail)
        if result.reason == daemon.AUTH_FAILED:
            daemon._log.critical(
                "startup self-check auth failure",
                reason=result.reason,
                detail=result.detail,
            )
        else:
            daemon._log.warning(
                "startup self-check not ready",
                reason=result.reason,
                detail=result.detail,
            )

    # on_online (D-02a + load-bearing ordering): the module fires this hook on the
    # first passing probe, THEN calls notifier.ready(). So starting the scheduler HERE
    # guarantees READY=1 reaches systemd STRICTLY AFTER scheduler.start() (the most
    # golden-sensitive invariant) — and after the durable online stamps + tick + the
    # structured log + the one-time Discord ping, in emit_online's EXACT order.
    def _on_online(_result) -> None:
        scheduler.start()
        daemon.stamp_health(db_path, reason="online")
        daemon.stamp_tick(db_path)
        daemon._log.info("weatherbot online", jobs=len(scheduler.get_jobs()))
        if channel is not None:
            send_result = channel.send(
                "WeatherBot online — startup self-check passed."
            )
            if send_result is not None and not getattr(send_result, "ok", True):
                daemon._log.warning(
                    "online ping not delivered",
                    detail=getattr(send_result, "detail", ""),
                )

    ready_gate = ReadyGate(
        _health_check,
        notifier,
        re_probe_interval=daemon.RE_PROBE_INTERVAL_S,
        on_online=_on_online,
        on_fail=_on_fail,
    )

    return RuntimeParts(
        scheduler=scheduler,
        stop=stop,
        holder=holder,
        cache=cache,
        channel=channel,
        bot=bot,
        reload_engine=reload_engine,
        ready_gate=ready_gate,
        notifier=notifier,
        identity=identity,
        started_at=started_at,
        watch=bool(config.reload.watch),
        config_path=config_path,
    )


def build_inbound_bot(
    token: str,
    *,
    holder: ConfigHolder,
    operator_id: int,
    cache: Any,
    daemon_state: Any,
):
    """Construct the inbound Discord ``BotThread`` at the single composition root (APP-01/02).

    The Phase-27 adapter rewire (SEAM-07, D-01/D-04/D-06): this is the ONE greppable injection
    site where the app threads its specifics into the relocated module adapter. It constructs
    the module :class:`~yahir_reusable_bot.discord.PanelKit` (injecting the app ``render`` via
    the ``_render_bridge`` closure, the app cosmetic contributors, ``marker=PANEL_MARKER``,
    ``operator_id``, the generic :class:`SelectedContext`, and the per-tap ``dispatch`` closure),
    builds the gateway client (the app ``on_message`` guard ladder + the injected ``!panel``
    summon + the persistent ``add_view`` of the panel), and returns the module ``BotThread``
    (NOT yet started — ``run_daemon`` starts it strictly after the READY signal, D-11).

    The lazy imports keep discord.py + the adapter off the import-time graph (the discipline
    ``build_runtime`` already follows for ``ForecastCache``). ``operator_id`` is baked at
    construction (preserve v1 — DEFERRED idea). The per-tap ``holder.current()`` reads survive
    inside the closures (Phase-24 hot-reload contract).
    """
    from yahir_reusable_bot.discord import (
        BotThread,
        PanelKit,
        SelectedContext,
        build_client,
    )

    from weatherbot.interactive import panel
    from weatherbot.interactive.bot import (
        build_on_message,
        build_panel_summon,
        render_embed,
    )
    from weatherbot.interactive.command import ForecastFlags
    from weatherbot.interactive.dispatch import dispatch_spec
    from weatherbot.interactive.lookup import UnknownLocationError
    from weatherbot.interactive.registry import BY_NAME
    from yahir_reusable_bot.discord.panelkit import DispatchOutcome

    # THE RENDER BRIDGE (D-01, RESEARCH Pattern 2): the module ``PanelKit`` calls its injected
    # ``render(reply, ctx)``; ``render_embed`` keeps its untouched ``location=`` kwarg. This
    # closure reconciles the signature mismatch WITHOUT editing ``render_embed`` — it forwards
    # ``ctx.value`` (the selected item, or ``None`` for an absent context) into the existing
    # ``location=`` kwarg, so the ``if location is not None`` 📍-suppression branch fires
    # identically. The module never names a render of its own.
    def _render_bridge(reply, ctx):
        return render_embed(reply, location=(ctx.value if ctx is not None else None))

    # THE DISPATCH CLOSURE (the on_command per-tap fetch path, D-01): the module ``on_command``
    # awaits ``dispatch(name, selection)`` and renders the returned ``DispatchOutcome``. This
    # app closure owns the per-tap ``holder.current()`` read, the arg adaptation
    # (``takes_location`` → the selected location or ``None``), the forecast-grid variant decode
    # (the app-encoded ``"<name>|<variant>"`` key → a DIRECT ``ForecastFlags``, Security V5),
    # the off-loop fetch via the shared ``dispatch_spec`` seam, and the ``UnknownLocationError``
    # → ``error_message`` branch (mirroring the v1 in-place CMD-02 error edit). The module
    # learns nothing about weather.
    async def _dispatch(name: str, selection) -> DispatchOutcome:
        loop = asyncio.get_running_loop()
        config = holder.current()  # per-tap snapshot (hot-reload picked up)
        decoded = panel.parse_forecast_dispatch_key(name)
        try:
            if decoded is not None:
                command_name, variant = decoded
                spec = BY_NAME[command_name]
                flags: ForecastFlags = panel.build_forecast_flags(
                    variant, selection.value
                )
                reply = await dispatch_spec(
                    spec,
                    None,  # the flags= path passes arg=None (D-01)
                    cache=cache,
                    config=config,
                    loop=loop,
                    daemon_state=daemon_state,
                    flags=flags,
                )
            else:
                spec = BY_NAME[name]
                arg = selection.value if spec.takes_location else None  # D-04
                reply = await dispatch_spec(
                    spec,
                    arg,
                    cache=cache,
                    config=config,
                    loop=loop,
                    daemon_state=daemon_state,
                )
        except UnknownLocationError as exc:
            # CMD-02 error path: the module edits in place with this message, no embed.
            return DispatchOutcome(error_message=str(exc))
        return DispatchOutcome(reply=reply)

    # The generic selected-item holder (D-02), seeded with the v1 default location (the first
    # configured location — mirrors resolve_location(config, None)).
    config = holder.current()
    locations = [loc.name for loc in config.locations]
    if not locations:
        raise ValueError(
            "panel requires at least one configured location; config.locations is empty"
        )
    selection: SelectedContext[str] = SelectedContext(locations[0])

    def _build_panelkit() -> PanelKit:
        # Each built PanelKit gets its OWN late-binding cell so its components resolve to IT
        # (not a later summon's fresh panel). The contributors dereference the cell only inside
        # their callbacks (post-construction); it is filled immediately after __init__ returns.
        panel_ref: list[PanelKit] = []
        kit = PanelKit(
            registry=_RegistryView(BY_NAME),
            command_names=panel.PANEL_COMMAND_NAMES,
            marker=panel.PANEL_MARKER,
            operator_id=operator_id,
            selection=selection,
            contributors=panel.build_contributors(panel_ref, holder),
            render=_render_bridge,
            dispatch=_dispatch,
            labels=panel.PANEL_LABELS,
            emoji=panel.PANEL_EMOJI,
            command_rows=panel.PANEL_COMMAND_ROWS,
        )
        panel_ref.append(kit)
        return kit

    panelkit = _build_panelkit()

    # The app summon closure (D-06): resolves panel_channel_id + builds the idle embed +
    # the panel factory, delegating the no-zero-panel-window ordering to the module. The idle
    # embed is argless (no location) → render_embed suppresses the 📍 line (byte-identical to
    # the v1 idle panel embed at bot.py:364).
    on_panel_summon = build_panel_summon(
        holder=holder,
        render=lambda reply: render_embed(reply),
        panel_factory=_build_panelkit,
        marker=panel.PANEL_MARKER,
    )

    handler = build_on_message(
        holder=holder,
        operator_id=operator_id,
        cache=cache,
        daemon_state=daemon_state,
        on_panel_summon=on_panel_summon,
    )
    client = build_client(on_message=handler, view=panelkit)
    return BotThread(token, client=client)


class _RegistryView:
    """Adapt the app's ``BY_NAME`` dict to the module ``PanelKit``'s ``registry.by_name`` read.

    ``PanelKit._build_command_buttons`` reads ``getattr(registry, "by_name", {})`` to resolve
    each curated command name. The app's command set is the import-time ``registry.BY_NAME``
    dict (the Phase-26 thin singleton); this thin view exposes it under the ``.by_name``
    attribute the module expects, without threading the whole registry module.
    """

    def __init__(self, by_name: dict) -> None:
        self.by_name = by_name
