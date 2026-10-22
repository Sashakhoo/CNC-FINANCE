"""default configuration: training programmes and scoring settings

Revision ID: a1b2c3d4e5f6
Revises: 55c19b4bff17
Create Date: 2026-10-22 15:00:00
"""
import json

import sqlalchemy as sa
from alembic import op

from app.services.defaults import DEFAULT_SETTINGS, TRAINING_PROGRAMS

revision = "a1b2c3d4e5f6"
down_revision = "55c19b4bff17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    for code, name, desc, depts, keywords in TRAINING_PROGRAMS:
        conn.execute(sa.text(
            "INSERT INTO training_programs (code, name, description, target_departments, keywords, enabled) "
            "VALUES (:c, :n, :d, CAST(:t AS jsonb), CAST(:k AS jsonb), true) ON CONFLICT (code) DO NOTHING"),
            {"c": code, "n": name, "d": desc, "t": json.dumps(depts), "k": json.dumps(keywords)})
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(sa.text(
            "INSERT INTO settings (key, value, version) VALUES (:k, CAST(:v AS jsonb), 1) ON CONFLICT (key) DO NOTHING"),
            {"k": key, "v": json.dumps(value)})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM settings WHERE key = ANY(:k)"), {"k": list(DEFAULT_SETTINGS)})
    conn.execute(sa.text("DELETE FROM training_programs WHERE code = ANY(:c)"), {"c": [p[0] for p in TRAINING_PROGRAMS]})
