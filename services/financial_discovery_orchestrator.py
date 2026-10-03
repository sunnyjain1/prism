"""
Financial Discovery Orchestrator
=================================
Single entry point to discover all of a user's financial accounts, investments,
retirement products, credit data, and alternative assets in one coordinated flow.

Runs 5 sequential phases via the existing JobQueue (ThreadPoolExecutor).
Each phase writes per-phase progress into DiscoverySession.phases_json so the
client can poll for real-time status.

Phases:
  A  bank_accounts   — Bank / savings / current / FD / credit cards / loans via AA
  B  investments     — MF / stocks / ETF / demat via AA
  C  retirement      — EPF / PPF / NPS via AA or EPFO stub
  D  credit_report   — Credit score + accounts via CreditScoreService
  E  alternative     — Gold / Silver / Real Estate (marks requires_manual_setup)
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models import (
    AggregatedAsset,
    DataSourceConnection,
    ConnectionStatus,
    DataSourceType,
    DiscoveryAuditLog,
    DiscoverySession,
)
from services.account_aggregator_service import AccountAggregatorService
from services.credit_score_service import fetch_credit_report
from services.job_queue import job_queue

logger = logging.getLogger(__name__)

ALL_PHASES = ["bank_accounts", "investments", "retirement", "credit_report", "alternative"]

_PHASE_STATUS_NOT_STARTED = "not_started"
_PHASE_STATUS_RUNNING = "running"
_PHASE_STATUS_COMPLETED = "completed"
_PHASE_STATUS_FAILED = "failed"
_PHASE_STATUS_SKIPPED = "skipped"


class FinancialDiscoveryOrchestrator:
    """Orchestrates multi-phase financial discovery for a user."""

    def __init__(self, db: Session):
        self.db = db
        self.aa_service = AccountAggregatorService(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_discovery(
        self,
        user_id: str,
        categories: Optional[list[str]] = None,
    ) -> DiscoverySession:
        """
        Create a DiscoverySession and enqueue the background job.
        Returns the session immediately so the caller can return session_id
        to the client for polling.
        """
        phases = categories if categories else ALL_PHASES[:]
        # Validate requested phases
        phases = [p for p in phases if p in ALL_PHASES]
        if not phases:
            phases = ALL_PHASES[:]

        initial_phases_json = {
            phase: {
                "status": _PHASE_STATUS_NOT_STARTED,
                "started_at": None,
                "completed_at": None,
                "error": None,
                "requires_manual_setup": False,
            }
            for phase in ALL_PHASES
        }
        # Mark skipped phases
        for phase in ALL_PHASES:
            if phase not in phases:
                initial_phases_json[phase]["status"] = _PHASE_STATUS_SKIPPED

        session = DiscoverySession(
            user_id=user_id,
            status="queued",
            phases_json=json.dumps(initial_phases_json),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        self._emit_audit_log(
            user_id=user_id,
            event_type="discovery_started",
            entity_type="discovery_session",
            entity_id=session.id,
            metadata={"phases": phases},
        )

        job_id = job_queue.enqueue(
            "financial_discovery",
            self._run_discovery,
            session.id,
            user_id,
            phases,
            user_id=user_id,
        )

        session.job_id = job_id
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session_status(self, session_id: str, user_id: str) -> Optional[DiscoverySession]:
        """Return a specific discovery session (must belong to the user)."""
        return (
            self.db.query(DiscoverySession)
            .filter(
                DiscoverySession.id == session_id,
                DiscoverySession.user_id == user_id,
            )
            .first()
        )

    def get_latest_session(self, user_id: str) -> Optional[DiscoverySession]:
        """Return the most recent discovery session for this user."""
        return (
            self.db.query(DiscoverySession)
            .filter(DiscoverySession.user_id == user_id)
            .order_by(DiscoverySession.created_at.desc())
            .first()
        )

    def get_sessions(self, user_id: str, limit: int = 10) -> list[DiscoverySession]:
        return (
            self.db.query(DiscoverySession)
            .filter(DiscoverySession.user_id == user_id)
            .order_by(DiscoverySession.created_at.desc())
            .limit(limit)
            .all()
        )

    def build_sync_status(self, user_id: str) -> dict[str, Any]:
        """
        Build an overall sync status object across all DataSourceConnections,
        categorised by asset type.
        """
        connections = (
            self.db.query(DataSourceConnection)
            .filter(DataSourceConnection.user_id == user_id)
            .all()
        )
        assets = (
            self.db.query(AggregatedAsset)
            .filter(AggregatedAsset.user_id == user_id)
            .all()
        )

        any_running = any(c.status == ConnectionStatus.syncing.value for c in connections)
        last_synced = max(
            (c.last_synced_at for c in connections if c.last_synced_at), default=None
        )

        def _category_status(types: list[str]) -> dict[str, Any]:
            relevant = [c for c in connections if c.source_type in types]
            asset_count = sum(
                1 for a in assets if a.asset_type in types
            )
            sync_at = max((c.last_synced_at for c in relevant if c.last_synced_at), default=None)
            status = "running" if any(c.status == ConnectionStatus.syncing.value for c in relevant) else (
                "idle" if not relevant else "synced"
            )
            return {"status": status, "last_sync": sync_at, "asset_count": asset_count}

        return {
            "overall_status": "running" if any_running else "idle",
            "started_at": None,
            "completed_at": last_synced,
            "categories": {
                "bank_accounts": _category_status([DataSourceType.bank_account.value, DataSourceType.credit_card.value]),
                "investments": _category_status([DataSourceType.mutual_fund.value, DataSourceType.stock.value]),
                "retirement": _category_status([DataSourceType.epf.value, DataSourceType.nps.value]),
                "credit_report": _category_status([DataSourceType.credit_bureau.value]),
            },
        }

    def sync_all(self, user_id: str) -> str:
        """
        Trigger a sync for all active DataSourceConnections.
        Runs as a background job. Returns job_id.
        """
        self._emit_audit_log(
            user_id=user_id,
            event_type="sync_started",
            entity_type=None,
            entity_id=None,
            metadata={},
        )
        job_id = job_queue.enqueue(
            "sync_all_connections",
            self._run_sync_all,
            user_id,
            user_id=user_id,
        )
        return job_id

    # ------------------------------------------------------------------
    # Background worker — runs inside JobQueue thread
    # ------------------------------------------------------------------

    def _run_discovery(self, session_id: str, user_id: str, phases: list[str]) -> dict[str, Any]:
        """Called by JobQueue worker thread. Runs phases sequentially."""
        db = SessionLocal()
        try:
            session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
            if not session:
                logger.error("DiscoverySession %s not found in worker", session_id)
                return {"error": "session not found"}

            session.status = "running"
            session.started_at = datetime.now(timezone.utc)
            db.commit()

            orchestrator = FinancialDiscoveryOrchestrator(db)
            phase_funcs = {
                "bank_accounts": orchestrator._run_phase_bank_accounts,
                "investments": orchestrator._run_phase_investments,
                "retirement": orchestrator._run_phase_retirement,
                "credit_report": orchestrator._run_phase_credit_report,
                "alternative": orchestrator._run_phase_alternative_assets,
            }

            phases_data: dict[str, Any] = json.loads(session.phases_json or "{}")
            any_failed = False

            for phase_id in ALL_PHASES:
                if phases_data.get(phase_id, {}).get("status") == _PHASE_STATUS_SKIPPED:
                    continue
                if phase_id not in phases:
                    continue

                phases_data[phase_id]["status"] = _PHASE_STATUS_RUNNING
                phases_data[phase_id]["started_at"] = datetime.now(timezone.utc).isoformat()
                session.phases_json = json.dumps(phases_data)
                db.commit()

                try:
                    result = phase_funcs[phase_id](session, user_id)
                    phases_data[phase_id]["status"] = _PHASE_STATUS_COMPLETED
                    phases_data[phase_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                    if result:
                        phases_data[phase_id].update(result)
                except Exception as exc:
                    logger.exception("Discovery phase %s failed for user %s: %s", phase_id, user_id, exc)
                    phases_data[phase_id]["status"] = _PHASE_STATUS_FAILED
                    phases_data[phase_id]["error"] = str(exc)
                    phases_data[phase_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                    any_failed = True

                session.phases_json = json.dumps(phases_data)
                db.commit()

            session.status = "partial_success" if any_failed else "completed"
            session.completed_at = datetime.now(timezone.utc)
            session.phases_json = json.dumps(phases_data)
            db.commit()

            orchestrator._emit_audit_log(
                user_id=user_id,
                event_type="discovery_completed" if not any_failed else "discovery_failed",
                entity_type="discovery_session",
                entity_id=session_id,
                metadata={"status": session.status},
            )

            return {"session_id": session_id, "status": session.status}

        except Exception as exc:
            logger.exception("Discovery worker crashed for session %s: %s", session_id, exc)
            try:
                session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
                if session:
                    session.status = "failed"
                    session.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                pass
            return {"error": str(exc)}
        finally:
            db.close()

    def _run_sync_all(self, user_id: str) -> dict[str, Any]:
        """Sync all active DataSourceConnections for a user."""
        db = SessionLocal()
        try:
            connections = (
                db.query(DataSourceConnection)
                .filter(
                    DataSourceConnection.user_id == user_id,
                    DataSourceConnection.status == ConnectionStatus.active.value,
                )
                .all()
            )
            results = []
            for conn in connections:
                try:
                    conn.status = ConnectionStatus.syncing.value
                    db.commit()
                    # Real sync implementation per source_type would go here.
                    # For now we simulate completion.
                    conn.status = ConnectionStatus.active.value
                    conn.last_synced_at = datetime.now(timezone.utc)
                    db.commit()
                    results.append({"connection_id": conn.id, "status": "success"})
                except Exception as exc:
                    conn.status = ConnectionStatus.error.value
                    conn.error_message = str(exc)
                    db.commit()
                    results.append({"connection_id": conn.id, "status": "failed", "error": str(exc)})

            orchestrator = FinancialDiscoveryOrchestrator(db)
            orchestrator._emit_audit_log(
                user_id=user_id,
                event_type="sync_completed",
                entity_type=None,
                entity_id=None,
                metadata={"connections_synced": len(results)},
            )
            return {"synced": len(results), "results": results}
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    def _run_phase_bank_accounts(self, session: DiscoverySession, user_id: str) -> dict[str, Any]:
        """
        Phase A: Import bank/savings/FD/credit card/loan accounts via AA.

        The consent handshake is user-driven (mobile OTP on the AA hosted page), so
        this phase fetches against an already-APPROVED consent. If none exists, the
        client must run the "Link bank accounts" flow first.
        """
        consent = self.aa_service.get_latest_approved_consent(user_id)
        if not consent:
            return {
                "requires_manual_setup": True,
                "accounts_discovered": 0,
                "note": "Link your bank via Account Aggregator to auto-import accounts.",
            }

        summary = self.aa_service.fetch_and_materialize(consent.id, user_id)
        return {
            "accounts_discovered": summary.get("accounts_created", 0) + summary.get("accounts_updated", 0),
            "connections_created": summary.get("accounts_created", 0),
            **summary,
        }

    def _run_phase_investments(self, session: DiscoverySession, user_id: str) -> dict[str, Any]:
        """Phase B: MF/stocks/ETF — placeholder connections (AA fetch out of current scope)."""
        self._upsert_connection(user_id, DataSourceType.mutual_fund.value, "CAMS", "CAMS MF Holdings", None)
        self._upsert_connection(user_id, DataSourceType.stock.value, "CDSL", "CDSL Demat Holdings", None)
        return {"status": "pending_aa_callback", "note": "MF/securities via AA — coming soon"}

    def _run_phase_retirement(self, session: DiscoverySession, user_id: str) -> dict[str, Any]:
        """Phase C: Discover EPF/PPF/NPS."""
        self._upsert_connection(user_id, DataSourceType.epf.value, "EPFO", "EPFO EPF Balance", None)
        self._upsert_connection(user_id, DataSourceType.nps.value, "NPS Trust", "NPS Pension Account", None)
        return {"note": "EPF and NPS integration pending EPFO/NPS API access"}

    def _run_phase_credit_report(self, session: DiscoverySession, user_id: str) -> dict[str, Any]:
        """Phase D: Fetch credit report and score via CreditScoreService."""
        report = fetch_credit_report(
            db=self.db,
            user_id=user_id,
            provider="cibil",
            pan=None,
        )
        self._upsert_connection(user_id, DataSourceType.credit_bureau.value, "CIBIL", "CIBIL Credit Report", None)
        return {"credit_score": report.score if report else None}

    def _run_phase_alternative_assets(self, session: DiscoverySession, user_id: str) -> dict[str, Any]:
        """Phase E: Alternative assets (Gold/Silver/Real Estate) require manual entry."""
        # Mark in phases_json that manual setup is required
        return {
            "requires_manual_setup": True,
            "asset_types": ["gold", "silver", "real_estate"],
            "note": "Add these assets manually from the Net Worth Hub",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _upsert_connection(
        self,
        user_id: str,
        source_type: str,
        provider_name: str,
        display_name: str,
        consent_id: Optional[str],
    ) -> DataSourceConnection:
        existing = (
            self.db.query(DataSourceConnection)
            .filter(
                DataSourceConnection.user_id == user_id,
                DataSourceConnection.provider_name == provider_name,
                DataSourceConnection.source_type == source_type,
            )
            .first()
        )
        if existing:
            existing.status = ConnectionStatus.active.value
            existing.last_synced_at = datetime.now(timezone.utc)
            if consent_id:
                existing.consent_id = consent_id
            self.db.commit()
            return existing

        conn = DataSourceConnection(
            user_id=user_id,
            source_type=source_type,
            provider_name=provider_name,
            display_name=display_name,
            status=ConnectionStatus.active.value,
            consent_id=consent_id,
            last_synced_at=datetime.now(timezone.utc),
        )
        self.db.add(conn)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def _emit_audit_log(
        self,
        user_id: str,
        event_type: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        metadata: dict[str, Any],
    ) -> None:
        try:
            log = DiscoveryAuditLog(
                user_id=user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata_json=json.dumps(metadata, default=str),
            )
            self.db.add(log)
            self.db.commit()
        except Exception as exc:
            logger.warning("Failed to write audit log (%s): %s", event_type, exc)
