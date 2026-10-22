"""schools segment: two programmes, school titles and the Schools target industry

Adds only what's missing — customised scoring settings are kept.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-23 00:00:00
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

PROGRAMS = [
    ("AI_FOR_EDUCATORS", "AI for Educators", "Practical AI for teachers: lesson planning, assessment and classroom use.",
     ["L&D", "IT"], ["teachers", "educators", "professional development", "digital learning", "edtech",
                     "teaching and learning", "staff development"]),
    ("CODING_FOR_STUDENTS", "Coding & AI for Students", "Coding, robotics and AI programmes for students — clubs, camps and enrichment.",
     ["IT", "L&D"], ["stem", "coding", "robotics", "computing", "computer science", "ict", "co-curricular",
                     "enrichment", "holiday programme", "after-school"]),
]
TITLES = {"Principal": 28, "Vice Principal": 24, "Director of Studies": 26, "Head of ICT/Computing": 26,
          "Head of STEM": 24, "Bursar": 12}


def upgrade() -> None:
    conn = op.get_bind()
    for code, name, desc, depts, keywords in PROGRAMS:
        conn.execute(sa.text(
            "INSERT INTO training_programs (code, name, description, target_departments, keywords, enabled) "
            "VALUES (:c, :n, :d, CAST(:t AS jsonb), CAST(:k AS jsonb), true) ON CONFLICT (code) DO NOTHING"),
            {"c": code, "n": name, "d": desc, "t": json.dumps(depts), "k": json.dumps(keywords)})
    row = conn.execute(sa.text("SELECT value FROM settings WHERE key = 'lead_scoring'")).first()
    if row:
        value = dict(row[0])
        titles = dict(value.get("titles") or {})
        for t, pts in TITLES.items():
            titles.setdefault(t, pts)
        value["titles"] = titles
        industries = list(value.get("target_industries") or [])
        if "Schools" not in industries:
            industries.append("Schools")
        value["target_industries"] = industries
        conn.execute(sa.text("UPDATE settings SET value = CAST(:v AS jsonb), version = version + 1 WHERE key = 'lead_scoring'"),
                     {"v": json.dumps(value)})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM training_programs WHERE code = ANY(:c)"), {"c": [p[0] for p in PROGRAMS]})
