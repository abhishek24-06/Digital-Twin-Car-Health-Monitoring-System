"""Gate-controlled smoke test for the Phase 4 agent LLM path.

Requires a real provider key (OpenRouter or Groq) in ``.env`` and runs only
when ``RUN_LLM_SMOKE_TEST=true`` so that the scheduled test suite never hits a
paid API. When the gate is off (or no provider is configured) the script
prints ``SKIPPED`` and exits 0.

Usage: ``RUN_LLM_SMOKE_TEST=true python -m scripts.smoke_agent_llm``
       (or ``make agent-llm-smoke``).
"""

from __future__ import annotations

import asyncio
import sys

from app.agent.config import get_agent_settings
from app.agent.service import AgentService
from app.agent.triggers import TriggerType
from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.logging import configure_logging
from app.repositories.agent_diagnosis_repository import AgentDiagnosisRepository
from scripts.seed_demo_vehicle import DEMO_VEHICLE_ID

SKIP_MESSAGE = (
    "SKIPPED: RUN_LLM_SMOKE_TEST is not 'true' or no LLM provider key is "
    "configured in .env (openrouter_api_key/groq_api_key)."
)


async def _run_smoke(session) -> None:
    settings = get_agent_settings()
    enabled = settings.run_llm_smoke_test
    if not enabled or not (settings.openrouter_api_key or settings.groq_api_key):
        print(SKIP_MESSAGE)
        return

    service = AgentService(session)
    response = await service.run_user_query(
        DEMO_VEHICLE_ID,
        "Summarize the current health of this vehicle and flag anything that needs attention.",
    )
    print(f"trigger_type      : {response.trigger_type}")
    print(f"severity          : {response.severity}")
    print(f"confidence        : {response.confidence:.3f}")
    print(f"provider          : {response.execution.provider} / {response.execution.model}")
    print(f"fallback used     : {response.execution.fallback_used}")
    print(f"latency_ms        : {response.execution.latency_ms:.1f}")
    print(
        f"tokens in/out     : {response.execution.input_tokens}/{response.execution.output_tokens}"
    )
    print(f"summary           : {response.diagnosis.summary[:240]!r}")
    print(f"persisted id      : {response.id}")

    # History must now expose the smoke diagnosis.
    history = await AgentDiagnosisRepository(session).list_by_vehicle(
        DEMO_VEHICLE_ID, page=1, page_size=5
    )
    print(f"history total     : {history[1]} (latest trigger {history[0][0].trigger_type})")


async def main() -> None:
    configure_logging()
    init_engine(get_settings())
    async with get_session_factory()() as session:
        latest = await AgentDiagnosisRepository(session).get_latest_by_vehicle(
            DEMO_VEHICLE_ID, trigger_type=TriggerType.USER_QUERY, status="completed"
        )
        if (
            latest is not None
            and input(
                f"A prior diagnosis exists from {latest.created_at.isoformat()}; run "
                "the smoke anyway? [y/N] "
            )
            .strip()
            .lower()
            != "y"
        ):
            print("SKIPPED: user declined.")
            return
        await _run_smoke(session)
    await dispose_engine()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
