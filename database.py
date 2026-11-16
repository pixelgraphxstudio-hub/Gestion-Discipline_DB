# -*- coding: utf-8 -*-
"""
database.py - Configuration SQLAlchemy
Don Bosco - Gestion Discipline 2026-2027
Prêt pour PostgreSQL / Supabase (changer l'URI dans app.py)
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
