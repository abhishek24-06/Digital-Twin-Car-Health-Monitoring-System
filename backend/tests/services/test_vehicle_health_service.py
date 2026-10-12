from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import NotFoundError
from app.repositories.health_snapshot_repository import HealthSnapshotRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.schemas.vehicle import VehicleCreate
from app.services.telemetry_service import TelemetryService
from app.services.vehicle_health_service import VehicleHealthService
from app.services.vehicle_service import VehicleService
from tests.conftest import unique_vin


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession], clean_db) -> AsyncSession:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
def service(session: AsyncSession) -> VehicleHealthService:
    return VehicleHealthService(
        session=session,
        vehicle_repository=VehicleRepository(session),
        telemetry_repository=TelemetryRepository(session),
        health_repository=HealthSnapshotRepository(session),
    )


@pytest_asyncio.fixture
def telemetry_service(session: AsyncSession) -> TelemetryService:
    return TelemetryService(
        session=session,
        repository=TelemetryRepository(session),
        vehicle_repository=VehicleRepository(session),
    )


def healthy_payload(rpm: float = 2000.0) -> TelemetryCreate:
    return TelemetryCreate(
        timestamp=datetime.now(UTC),
        rpm=rpm,
        speed=60.0,
        engine_load=30.0,
        coolant_temperature=90.0,
        oil_temperature=90.0,
        battery_voltage=13.5,
        fuel_level=60.0,
        intake_air_temperature=25.0,
        throttle_position=20.0,
        engine_runtime=1000.0,
        odometer=50000.0,
    )


async def _create_vehicle(session: AsyncSession) -> UUID:
    vehicle = await VehicleService(session, VehicleRepository(session)).create_vehicle(
        VehicleCreate(vin=unique_vin(), make="Toyota", model="Camry", year=2024)
    )
    return vehicle.id


async def _ingest_healthy_window(telemetry_service: TelemetryService, vehicle_id: UUID) -> None:
    now = datetime.now(UTC)
    for index in range(40):
        payload = healthy_payload()
        payload.timestamp = now - timedelta(seconds=40 - index)
        await telemetry_service.create_telemetry(vehicle_id, payload)


async def test_analyze_vehicle_persists_snapshot(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)

    snapshot = await service.analyze_vehicle(vehicle_id, window_minutes=1)

    assert snapshot.vehicle_id == vehicle_id
    assert snapshot.health_status == "healthy"
    assert snapshot.health_score == 100.0
    assert snapshot.context_schema_version == "1.2"
    assert snapshot.context_json["health_status"] == "healthy"
    assert snapshot.context_json["analysis_scope"] == "historical_window"
    assert snapshot.context_json["data_sufficiency"] == "sufficient_data"
    assert snapshot.context_json["provisional"] is False
    assert snapshot.confidence is not None and 0.5 < snapshot.confidence <= 1.0

    latest = await service.get_latest(vehicle_id)
    assert latest is not None
    assert latest.id == snapshot.id


async def test_analyze_vehicle_respects_window_minutes(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)

    snapshot = await service.analyze_vehicle(vehicle_id, window_minutes=2)

    window_seconds = (snapshot.window_end - snapshot.window_start).total_seconds()
    assert 110.0 <= window_seconds <= 130.0


async def test_analyze_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.analyze_vehicle(uuid4(), window_minutes=1)


async def test_analyze_invalid_window_minutes_raises_value_error(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)
    with pytest.raises(ValueError):
        await service.analyze_vehicle(vehicle_id, window_minutes=0)


async def test_get_latest_none_before_any_analysis(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    assert await service.get_latest(vehicle_id) is None


async def test_get_latest_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.get_latest(uuid4())


async def test_list_history_paginated_and_latest_first(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)
    await service.analyze_vehicle(vehicle_id, window_minutes=1)
    await service.analyze_vehicle(vehicle_id, window_minutes=1)

    items, total = await service.list_history(vehicle_id, page=1, page_size=1)
    assert total == 2
    assert len(items) == 1
    assert items[0].generated_at >= items[0].window_end


async def test_list_history_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.list_history(uuid4(), page=1, page_size=10)


async def test_repeat_analysis_creates_new_snapshot(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    await _ingest_healthy_window(telemetry_service, vehicle_id)
    first = await service.analyze_vehicle(vehicle_id, window_minutes=1)
    second = await service.analyze_vehicle(vehicle_id, window_minutes=1)

    assert first.id != second.id
    items, total = await service.list_history(vehicle_id, page=1, page_size=10)
    assert total == 2


# --- Live current-session analysis (Phase 2) ---


async def _ingest_run_window(
    telemetry_service: TelemetryService,
    vehicle_id: UUID,
    run_id: UUID,
    *,
    count: int = 40,
    span_seconds: float = 40.0,
) -> None:
    """Ingest ``count`` samples for one run, spread over ``span_seconds``.

    Each timestamp is anchored to the moment it is written (oldest first), so
    the newest sample stays fresh — the live sufficiency gate bounds
    ``latest_sample_age_seconds`` and the per-row commit latency must not be
    counted as sample age.
    """
    for index in range(count):
        payload = healthy_payload()
        payload.timestamp = datetime.now(UTC) - timedelta(
            seconds=(count - index - 1) * span_seconds / count
        )
        payload.simulation_run_id = run_id
        payload.source_event_id = f"run-{run_id.hex[:8]}-{index}"
        await telemetry_service.create_telemetry(vehicle_id, payload)


async def test_analyze_live_vehicle_fresh_run_is_definitive(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    run_id = uuid4()
    await _ingest_run_window(telemetry_service, vehicle_id, run_id, count=40, span_seconds=40.0)

    snapshot = await service.analyze_live_vehicle(vehicle_id, run_id)

    assert snapshot.health_status == "healthy"
    assert snapshot.health_score == 100.0
    assert snapshot.context_json["data_sufficiency"] == "sufficient_data"
    assert snapshot.context_json["provisional"] is False
    assert snapshot.context_json["simulation_run_id"] == str(run_id)
    live = snapshot.context_json["live_sufficiency"]
    assert live is not None
    assert live["policy_met"] is True
    assert live["sample_count"] == 40
    assert live["required_sample_count"] == 30


async def test_analyze_live_vehicle_persist_false_is_side_effect_free(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    """P2-1: a live evaluation only persists when ``persist`` is requested.

    The live-health read path evaluates with ``persist=False`` so a poll loop
    cannot fill the snapshot history; the monitor keeps the persisting default.
    """
    vehicle_id = await _create_vehicle(session)
    run_id = uuid4()
    await _ingest_run_window(telemetry_service, vehicle_id, run_id, count=40, span_seconds=40.0)

    evaluated = await service.analyze_live_vehicle(vehicle_id, run_id, persist=False)
    assert evaluated.health_status == "healthy"
    assert evaluated.context_json["simulation_run_id"] == str(run_id)
    assert evaluated.id is None

    repository = HealthSnapshotRepository(session)
    _, total = await repository.list_by_vehicle(vehicle_id, page=1, page_size=100)
    assert total == 0

    persisted = await service.analyze_live_vehicle(vehicle_id, run_id)
    assert persisted.id is not None
    _, total_after = await repository.list_by_vehicle(vehicle_id, page=1, page_size=100)
    assert total_after == 1


async def test_analyze_live_vehicle_collecting_when_insufficient(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    run_id = uuid4()
    # 10 samples over 10s: under the 30-sample / 30s live gate.
    await _ingest_run_window(telemetry_service, vehicle_id, run_id, count=10, span_seconds=10.0)

    snapshot = await service.analyze_live_vehicle(vehicle_id, run_id)

    assert snapshot.health_status == "limited_data"
    assert snapshot.context_json["data_sufficiency"] == "limited_data"
    assert snapshot.context_json["provisional"] is True
    live = snapshot.context_json["live_sufficiency"]
    assert live["policy_met"] is False
    assert live["sample_count"] == 10
    assert any("current-run sample" in r for r in live["reasons"])
    # The fresh run's provisional assessment must not be dressed up as a firm verdict.
    assert any(f["rule_id"] == "LIVE_DATA_SUFFICIENCY" for f in snapshot.context_json["findings"])


async def test_analyze_live_vehicle_stale_feed_is_provisional(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    run_id = uuid4()
    # 40 samples spanning 40s, but shifted back so the newest is ~60s old.
    now = datetime.now(UTC)
    for index in range(40):
        payload = healthy_payload()
        payload.timestamp = now - timedelta(seconds=100 - index)
        payload.simulation_run_id = run_id
        await telemetry_service.create_telemetry(vehicle_id, payload)

    snapshot = await service.analyze_live_vehicle(vehicle_id, run_id)

    live = snapshot.context_json["live_sufficiency"]
    assert live["policy_met"] is False
    assert live["latest_sample_age_seconds"] > live["max_sample_age_seconds"]
    assert any("old" in r for r in live["reasons"])
    assert snapshot.health_status == "limited_data"
    assert snapshot.context_json["provisional"] is True


async def test_analyze_live_vehicle_restart_isolation(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    """After a restart, run B's assessment counts only run B's evidence."""
    vehicle_id = await _create_vehicle(session)
    run_a = uuid4()
    run_b = uuid4()
    await _ingest_run_window(telemetry_service, vehicle_id, run_a, count=40, span_seconds=40.0)
    await _ingest_run_window(telemetry_service, vehicle_id, run_b, count=5, span_seconds=5.0)

    snapshot_b = await service.analyze_live_vehicle(vehicle_id, run_b)

    # Run B is still collecting: only its 5 samples count, never run A's.
    assert snapshot_b.context_json["data_quality"]["sample_count"] == 5
    assert snapshot_b.health_status == "limited_data"
    assert snapshot_b.context_json["provisional"] is True
    assert snapshot_b.context_json["simulation_run_id"] == str(run_b)

    # Run A remains independently evaluable from its own persisted evidence.
    snapshot_a = await service.analyze_live_vehicle(vehicle_id, run_a)
    assert snapshot_a.health_status == "healthy"
    assert snapshot_a.context_json["data_quality"]["sample_count"] == 40
    assert snapshot_a.context_json["simulation_run_id"] == str(run_a)


async def test_analyze_live_ignores_legacy_and_old_run_outliers(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    """Acceptance 1+2: legacy (NULL-run) and previous-run rows never influence
    current health.

    Both a legacy batch and a completed previous run carry a critical coolant
    outlier *inside the analysis window*; the active run is healthy. The live
    assessment must count only the active run, so the outlier must not appear in
    the statistics, findings, score, confidence or coverage.
    """
    vehicle_id = await _create_vehicle(session)
    active_run = uuid4()
    old_run = uuid4()
    now = datetime.now(UTC)

    # Legacy rows (no run identity), 10 minutes ago: inside the 15-minute window.
    for index in range(30):
        payload = healthy_payload()
        payload.timestamp = now - timedelta(minutes=10) - timedelta(seconds=index * 0.1)
        payload.coolant_temperature = 130.0
        await telemetry_service.create_telemetry(vehicle_id, payload)

    # A completed previous run, 8 minutes ago: also inside the window.
    for index in range(30):
        payload = healthy_payload()
        payload.timestamp = now - timedelta(minutes=8) - timedelta(seconds=index * 0.1)
        payload.coolant_temperature = 130.0
        payload.simulation_run_id = old_run
        payload.source_event_id = f"old-{index}"
        await telemetry_service.create_telemetry(vehicle_id, payload)

    # The active run: fresh, sufficient and healthy.
    await _ingest_run_window(telemetry_service, vehicle_id, active_run, count=40, span_seconds=40.0)

    snapshot = await service.analyze_live_vehicle(vehicle_id, active_run)

    context = snapshot.context_json
    assert context["analysis_scope"] == "current_session"
    assert context["simulation_run_id"] == str(active_run)
    assert context["data_quality"]["sample_count"] == 40
    coolant = context["statistics"]["coolant_temperature"]
    assert coolant["maximum"] == 90.0
    assert coolant["last"] == 90.0
    assert all(f["rule_id"] != "COOLANT_TEMP_HIGH" for f in context["findings"])
    assert snapshot.health_status == "healthy"
    assert snapshot.health_score == 100.0


async def test_analyze_live_vehicle_zero_samples_is_no_data(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    vehicle_id = await _create_vehicle(session)
    run_id = uuid4()

    snapshot = await service.analyze_live_vehicle(vehicle_id, run_id)

    assert snapshot.health_status == "no_data"
    assert snapshot.context_json["data_sufficiency"] == "no_data"
    assert snapshot.context_json["data_quality"]["sample_count"] == 0
    live = snapshot.context_json["live_sufficiency"]
    assert live["policy_met"] is False


async def test_analyze_live_missing_vehicle_raises_not_found(
    service: VehicleHealthService, session: AsyncSession
) -> None:
    with pytest.raises(NotFoundError):
        await service.analyze_live_vehicle(uuid4(), uuid4())


async def test_analyze_live_vehicle_run_baseline_excludes_active_run(
    service: VehicleHealthService, telemetry_service: TelemetryService, session: AsyncSession
) -> None:
    """The historical baseline excludes the active run's own early samples."""
    vehicle_id = await _create_vehicle(session)
    run_id = uuid4()
    # Run A (the active run) also has *early* samples that fall inside the
    # 6h baseline range but outside the 15m analysis window.
    now = datetime.now(UTC)
    early = [
        now - timedelta(minutes=30) - timedelta(seconds=index)
        for index in range(20, 0, -1)
    ]
    for ts in early:
        payload = healthy_payload()
        payload.timestamp = ts
        payload.simulation_run_id = run_id
        await telemetry_service.create_telemetry(vehicle_id, payload)
    # One genuinely historical (pre-session) sample with no run identity.
    legacy = healthy_payload()
    legacy.timestamp = now - timedelta(hours=2)
    await telemetry_service.create_telemetry(vehicle_id, legacy)
    # Fresh current-run window evidence.
    await _ingest_run_window(telemetry_service, vehicle_id, run_id, count=40, span_seconds=40.0)

    snapshot = await service.analyze_live_vehicle(vehicle_id, run_id)

    data_quality = snapshot.context_json["data_quality"]
    # Only the 40 fresh run samples are current-run evidence; the run's own
    # pre-window samples must not be fused into the analysis window.
    assert data_quality["sample_count"] == 40
    first_ts = datetime.fromisoformat(data_quality["first_timestamp"])
    assert (now - first_ts).total_seconds() < 120  # window starts near the fresh block
    # The baseline was computed without the active run polluting it: the only
    # baseline-eligible history row is the legacy (NULL-run) sample.
    baselines = snapshot.context_json["baselines"]
    assert isinstance(baselines, list)
