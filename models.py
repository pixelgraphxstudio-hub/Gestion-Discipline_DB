# -*- coding: utf-8 -*-
"""
models.py - 6 tables de la base de données
Don Bosco - Gestion Discipline 2026-2027

Roles utilisateurs : surveillant_general / surveillant (PAS de directeur)
"""

from datetime import datetime
from database import db
from werkzeug.security import generate_password_hash, check_password_hash


class Eleve(db.Model):
    __tablename__ = 'eleves'

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, nullable=True, index=True)
    classe = db.Column(db.String(20), nullable=False, index=True)
    prenoms = db.Column(db.String(150), nullable=False)
    nom = db.Column(db.String(150), nullable=False)
    nom_complet = db.Column(db.String(300), nullable=False)
    actif = db.Column(db.Boolean, default=True)

    journal_entries = db.relationship(
        'Journal', backref='eleve', lazy='dynamic',
        cascade='all, delete-orphan'
    )
    fiches_renvoi = db.relationship(
        'FicheRenvoi', backref='eleve', lazy='dynamic'
    )

    def __repr__(self):
        return f'<Eleve {self.nom_complet} ({self.classe})>'

    @property
    def retards(self):
        return self.journal_entries.filter_by(type='Retard').count()

    @property
    def absences(self):
        return self.journal_entries.filter_by(type='Absence').count()

    @property
    def absences_non_justifiees(self):
        return self.journal_entries.filter_by(
            type='Absence', justifie='Non'
        ).count()

    @property
    def renvois(self):
        return self.journal_entries.filter_by(type='Renvoi').count()

    @property
    def statut(self):
        from models import Parametre
        p = Parametre.get()
        if p is None:
            return 'OK'
        if self.renvois >= p.seuil_renvoi:
            return 'À CONVOQUER'
        if self.retards >= p.seuil_retard or self.absences_non_justifiees >= p.seuil_absence_non_justifiee:
            return 'À SURVEILLER'
        return 'OK'

    @property
    def statut_couleur(self):
        s = self.statut
        if s == 'À CONVOQUER':
            return 'danger'
        if s == 'À SURVEILLER':
            return 'warning'
        return 'success'


class Journal(db.Model):
    __tablename__ = 'journal'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    classe = db.Column(db.String(20), nullable=False, index=True)
    eleve_id = db.Column(db.Integer, db.ForeignKey('eleves.id'), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False, index=True)
    heure_seance = db.Column(db.String(20), nullable=True)
    justifie = db.Column(db.String(10), nullable=False, default='Non')
    motif = db.Column(db.Text, nullable=True)
    decision = db.Column(db.String(200), nullable=True)
    parents_informes = db.Column(db.String(10), nullable=False, default='Non')
    saisi_par_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    photo_justificatif = db.Column(db.String(300), nullable=True)

    saisi_par = db.relationship('Utilisateur', backref='journal_saisies')

    def __repr__(self):
        return f'<Journal {self.type} {self.eleve.nom_complet if self.eleve else ""}>'


class Utilisateur(db.Model):
    __tablename__ = 'utilisateurs'

    id = db.Column(db.Integer, primary_key=True)
    nom_complet = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='surveillant')
    telephone = db.Column(db.String(30), nullable=True)
    actif = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def est_surveillant_general(self):
        return self.role == 'surveillant_general'

    def peut_gerer_utilisateurs(self):
        return self.role == 'surveillant_general'

    def peut_gerer_parametres(self):
        return self.role == 'surveillant_general'

    def peut_modifier_tout_journal(self):
        return self.role == 'surveillant_general'

    def __repr__(self):
        return f'<Utilisateur {self.email} ({self.role})>'


class Parametre(db.Model):
    __tablename__ = 'parametres'

    id = db.Column(db.Integer, primary_key=True)
    seuil_retard = db.Column(db.Integer, default=3)
    seuil_absence_non_justifiee = db.Column(db.Integer, default=3)
    seuil_renvoi = db.Column(db.Integer, default=1)
    annee_scolaire = db.Column(db.String(20), default='2026-2027')
    nom_ecole = db.Column(db.String(200), default='Collège Don Bosco')

    @classmethod
    def get(cls):
        p = cls.query.first()
        if p is None:
            p = cls()
            db.session.add(p)
            db.session.commit()
        return p

    def __repr__(self):
        return f'<Parametre {self.annee_scolaire} - {self.nom_ecole}>'


class HistoriqueAction(db.Model):
    __tablename__ = 'historique_actions'

    id = db.Column(db.Integer, primary_key=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=False)
    date_action = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    utilisateur = db.relationship('Utilisateur', backref='historique')

    def __repr__(self):
        return f'<Historique {self.action} - {self.date_action}>'


class FicheRenvoi(db.Model):
    __tablename__ = 'fiches_renvoi'

    id = db.Column(db.Integer, primary_key=True)
    eleve_id = db.Column(db.Integer, db.ForeignKey('eleves.id'), nullable=False, index=True)
    date_renvoi = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    motif = db.Column(db.Text, nullable=False)
    duree = db.Column(db.String(50), nullable=False)
    retour_en_classe_le = db.Column(db.DateTime, nullable=True)
    cree_par_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    cree_par = db.relationship('Utilisateur', backref='fiches_creees')

    def __repr__(self):
        return f'<FicheRenvoi {self.eleve.nom_complet if self.eleve else ""} - {self.duree}>'


def ecrire_historique(utilisateur, action, details):
    try:
        hist = HistoriqueAction(
            utilisateur_id=utilisateur.id if utilisateur else None,
            action=action,
            details=details
        )
        db.session.add(hist)
        db.session.commit()
    except Exception:
        db.session.rollback()
