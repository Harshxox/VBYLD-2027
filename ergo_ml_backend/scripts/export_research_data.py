"""Backfill the automatic research CSV export for already completed sessions.

Run from ergo_ml_backend:
    python scripts/export_research_data.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal  # noqa: E402
from app.models.assessment import AssessmentSession  # noqa: E402
from app.models.sensors import SensorLink, SensorReading  # noqa: E402
from app.research_export import export_completed_session, write_data_dictionary  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    write_data_dictionary()
    db = SessionLocal()
    exported = 0
    try:
        sessions = (
            db.query(AssessmentSession)
            .filter(
                AssessmentSession.completed_at.isnot(None),
                AssessmentSession.report_json.isnot(None),
            )
            .order_by(AssessmentSession.completed_at)
            .all()
        )
        for session in sessions:
            link = db.query(SensorLink).filter(
                SensorLink.session_id == session.id
            ).first()
            readings = (
                db.query(SensorReading)
                .filter(SensorReading.session_id == session.id)
                .order_by(SensorReading.received_at, SensorReading.id)
                .all()
            )
            export_completed_session(
                session=session,
                answers=list(session.answers),
                readings=readings,
                link=link,
                report=session.report_json,
            )
            exported += 1
    finally:
        db.close()
    print(f"Exported {exported} completed session(s) to {os.path.abspath('./research_data')}")


if __name__ == "__main__":
    main()
