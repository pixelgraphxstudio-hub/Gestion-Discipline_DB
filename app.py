# -*- coding: utf-8 -*-
# app.py - Don Bosco - Gestion Discipline 2026-2027
# Deploiement : Render (connecter le repo GitHub)
# Aucun compte demo. Inscription obligatoire pour chaque surveillant.

import os
import io
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, send_file, make_response, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database import db, init_db
from models import (
    Eleve, Journal, Utilisateur, Parametre,
    HistoriqueAction, FicheRenvoi, ecrire_historique
)

try:
    import openpyxl
    HAS_OPENPYXL = True
except Exception:
    HAS_OPENPYXL = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    )
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'don-bosco-discipline-2026-2027')

app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL') or
    ('sqlite:///' + os.path.join(app.instance_path, 'don_bosco.db'))
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(
    app.root_path, 'static', 'uploads', 'justificatifs'
)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.instance_path, exist_ok=True)

init_db(app)

CLASSES = [
    '6IEME A', '6IEME B', '6IEME C',
    '5IEME A', '5IEME B', '5IEME C',
    '4IEME A', '4IEME B', '4IEME C',
    '3IEME A', '3IEME B', '3IEME C',
    '2NDE L', '2NDE S',
    '1ERE L', '1ERE S',
    'TLE L', 'TLE S',
]

TYPES_JOURNAL = ['Retard', 'Absence', 'Renvoi']
OUI_NON = ['Oui', 'Non']
MOTIFS_SUGGERES = [
    'Réveil tardif', 'Malade', 'Conjonctivite', 'Transport',
    'Famille', 'Rendez-vous', 'Sans motif', 'Autre'
]
ROLES = [
    ('surveillant_general', 'Surveillant Général'),
    ('surveillant', 'Surveillant'),
]


def est_connecte():
    return 'user_id' in session


def utilisateur_courant():
    if not est_connecte():
        return None
    return Utilisateur.query.get(session.get('user_id'))


def login_required(f):
    @wraps(f)
    def decoree(*args, **kwargs):
        if not est_connecte():
            flash('Connexion requise pour acceder a cette page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decoree


def role_required(*roles_autorises):
    def decorateur(f):
        @wraps(f)
        def decoree(*args, **kwargs):
            if not est_connecte():
                flash('Connexion requise.', 'warning')
                return redirect(url_for('login'))
            u = utilisateur_courant()
            if u is None or not u.actif or u.role not in roles_autorises:
                flash('Accès refusé : droits insuffisants.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decoree
    return decorateur


def peut_modifier_journal(entree):
    u = utilisateur_courant()
    if u is None:
        return False
    if u.est_surveillant_general():
        return True
    return entree.saisi_par_id == u.id


def date_db(valeur):
    if valeur is None or valeur == '':
        return datetime.utcnow()
    if isinstance(valeur, datetime):
        return valeur
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(valeur, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def fr_date(dt):
    if dt is None:
        return ''
    return dt.strftime('%d/%m/%Y')


def fr_datetime(dt):
    if dt is None:
        return ''
    return dt.strftime('%d/%m/%Y %H:%M')


@app.before_request
def _initialiser():
    if not hasattr(app, '_donnees_crees'):
        app._donnees_crees = True
        with app.app_context():
            db.create_all()


@app.context_processor
def injecter_contexte():
    u = utilisateur_courant()
    try:
        p = Parametre.get()
    except Exception:
        p = None
    return dict(u=u, p=p, CLASSES=CLASSES, ROLES=ROLES, peut_modifier_journal=peut_modifier_journal)


# ------------------------------------------------------------------
# Authentification : inscription + connexion
# ------------------------------------------------------------------
@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if est_connecte():
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nom_complet = request.form.get('nom_complet', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'surveillant')
        telephone = request.form.get('telephone', '').strip()

        if not nom_complet or not email or not password:
            flash('Tous les champs obligatoires doivent etre remplis.', 'danger')
            return render_template('inscription.html')
        if Utilisateur.query.filter_by(email=email).first():
            flash('Cet email est deja utilise.', 'danger')
            return render_template('inscription.html')

        u = Utilisateur(
            nom_complet=nom_complet,
            email=email,
            role=role,
            telephone=telephone,
            actif=True
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        ecrire_historique(u, 'INSCRIPTION', f'Nouveau compte cree : {email} ({role})')
        flash('Compte cree avec succès. Vous pouvez vous connecter.', 'success')
        return redirect(url_for('login'))
    return render_template('inscription.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if est_connecte():
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        u = Utilisateur.query.filter_by(email=email, actif=True).first()
        if u and u.check_password(password):
            session['user_id'] = u.id
            session['user_nom'] = u.nom_complet
            session['user_role'] = u.role
            session['user_email'] = u.email
            ecrire_historique(u, 'CONNEXION', f'{u.nom_complet} ({u.role}) connecte')
            flash(f'Bienvenue {u.nom_complet} !', 'success')
            return redirect(url_for('dashboard'))
        flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    u = utilisateur_courant()
    if u:
        ecrire_historique(u, 'DECONNEXION', f'{u.nom_complet} deconnecte')
    session.clear()
    flash('Vous avez été deconnecte.', 'info')
    return redirect(url_for('login'))


@app.route('/')
def index():
    if est_connecte():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    u = utilisateur_courant()
    aujourd_hui = datetime.utcnow().date()
    debut_jour = datetime.combine(aujourd_hui, datetime.min.time())
    fin_jour = datetime.combine(aujourd_hui, datetime.max.time())

    retards_aujourd_hui = Journal.query.filter(
        Journal.type == 'Retard',
        Journal.date >= debut_jour,
        Journal.date <= fin_jour
    ).count()
    absences_aujourd_hui = Journal.query.filter(
        Journal.type == 'Absence',
        Journal.date >= debut_jour,
        Journal.date <= fin_jour
    ).count()
    renvois_aujourd_hui = Journal.query.filter(
        Journal.type == 'Renvoi',
        Journal.date >= debut_jour,
        Journal.date <= fin_jour
    ).count()

    derniers = Journal.query.order_by(Journal.date_creation.desc()).limit(10).all()

    p = Parametre.get()
    eleves_convoquer = []
    for e in Eleve.query.filter_by(actif=True).all():
        if e.statut == 'À CONVOQUER':
            eleves_convoquer.append(e)
    eleves_convoquer = sorted(eleves_convoquer, key=lambda x: x.nom)[:20]
    nb_convoquer = len(eleves_convoquer)

    classes_graph, retards_graph, absences_graph, renvois_graph = [], [], [], []
    for cl in CLASSES:
        classes_graph.append(cl)
        r = Journal.query.filter_by(classe=cl, type='Retard').filter(
            Journal.date >= debut_jour, Journal.date <= fin_jour
        ).count()
        a = Journal.query.filter_by(classe=cl, type='Absence').filter(
            Journal.date >= debut_jour, Journal.date <= fin_jour
        ).count()
        rn = Journal.query.filter_by(classe=cl, type='Renvoi').filter(
            Journal.date >= debut_jour, Journal.date <= fin_jour
        ).count()
        retards_graph.append(r)
        absences_graph.append(a)
        renvois_graph.append(rn)

    return render_template(
        'dashboard.html',
        u=u,
        retards_aujourd_hui=retards_aujourd_hui,
        absences_aujourd_hui=absences_aujourd_hui,
        renvois_aujourd_hui=renvois_aujourd_hui,
        derniers=derniers,
        eleves_convoquer=eleves_convoquer,
        nb_convoquer=nb_convoquer,
        classes_graph=classes_graph,
        retards_graph=retards_graph,
        absences_graph=absences_graph,
        renvois_graph=renvois_graph,
        now=datetime.now()
    )


# ------------------------------------------------------------------
# Journal
# ------------------------------------------------------------------
@app.route('/journal')
@login_required
def journal():
    u = utilisateur_courant()
    page = request.args.get('page', 1, type=int)
    recherche = request.args.get('recherche', '').strip()
    filtre_classe = request.args.get('classe', '').strip()
    filtre_date_debut = request.args.get('date_debut', '').strip()
    filtre_date_fin = request.args.get('date_fin', '').strip()
    filtre_type = request.args.get('type', '').strip()
    filtre_justifie = request.args.get('justifie', '').strip()

    q = Journal.query.join(Eleve, Journal.eleve_id == Eleve.id)

    if recherche:
        q = q.filter(
            (Eleve.nom.ilike(f'%{recherche}%')) |
            (Eleve.prenoms.ilike(f'%{recherche}%')) |
            (Eleve.nom_complet.ilike(f'%{recherche}%'))
        )
    if filtre_classe:
        q = q.filter(Journal.classe == filtre_classe)
    if filtre_type:
        q = q.filter(Journal.type == filtre_type)
    if filtre_justifie:
        q = q.filter(Journal.justifie == filtre_justifie)
    if filtre_date_debut:
        try:
            q = q.filter(Journal.date >= datetime.strptime(filtre_date_debut, '%Y-%m-%d'))
        except ValueError:
            pass
    if filtre_date_fin:
        try:
            d = datetime.strptime(filtre_date_fin, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(Journal.date < d)
        except ValueError:
            pass

    q = q.order_by(Journal.date.desc(), Journal.date_creation.desc())
    pagination = q.paginate(page=page, per_page=50, error_out=False)

    eleves_par_classe = {}
    for e in Eleve.query.filter_by(actif=True).all():
        eleves_par_classe.setdefault(e.classe, []).append({
            'id': e.id,
            'nom_complet': e.nom_complet,
            'numero': e.numero,
        })
    import json as _json
    eleves_json = _json.dumps(eleves_par_classe, ensure_ascii=False)

    return render_template(
        'journal.html',
        u=u,
        entrees=pagination.items,
        pagination=pagination,
        classes=CLASSES,
        recherche=recherche,
        filtre_classe=filtre_classe,
        filtre_date_debut=filtre_date_debut,
        filtre_date_fin=filtre_date_fin,
        filtre_type=filtre_type,
        filtre_justifie=filtre_justifie,
        eleves_json=eleves_json,
        types=TYPES_JOURNAL,
        oui_non=OUI_NON,
        motifs=MOTIFS_SUGGERES,
        now=datetime.now()
    )


@app.route('/journal/ajouter', methods=['POST'])
@login_required
def journal_ajouter():
    u = utilisateur_courant()
    eleve_id = request.form.get('eleve_id', type=int)
    if not eleve_id:
        flash('Veuillez selectionner un eleve.', 'danger')
        return redirect(url_for('journal'))

    eleve = Eleve.query.get(eleve_id)
    if eleve is None:
        flash('Eleve introuvable.', 'danger')
        return redirect(url_for('journal'))

    entree = Journal(
        date=date_db(request.form.get('date')),
        classe=eleve.classe,
        eleve_id=eleve.id,
        type=request.form.get('type', 'Retard'),
        heure_seance=request.form.get('heure_seance', '').strip() or None,
        justifie=request.form.get('justifie', 'Non'),
        motif=request.form.get('motif', '').strip() or None,
        decision=request.form.get('decision', '').strip() or None,
        parents_informes=request.form.get('parents_informes', 'Non'),
        saisi_par_id=u.id,
    )

    photo = request.files.get('photo_justificatif')
    if photo and photo.filename:
        filename = secure_filename(photo.filename)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        entree.photo_justificatif = filename

    db.session.add(entree)
    db.session.commit()
    ecrire_historique(
        u, 'AJOUT',
        f"{u.nom_complet} a ajoute un {entree.type} pour {eleve.nom_complet} "
        f"({eleve.classe}) le {fr_date(entree.date)}."
    )
    flash(f'{entree.type} enregistre pour {eleve.nom_complet}.', 'success')
    return redirect(url_for('journal'))


@app.route('/journal/<int:entree_id>/modifier', methods=['GET', 'POST'])
@login_required
def journal_modifier(entree_id):
    u = utilisateur_courant()
    entree = Journal.query.get_or_404(entree_id)
    if not peut_modifier_journal(entree):
        flash('Vous ne pouvez modifier que vos propres saisies.', 'danger')
        return redirect(url_for('journal'))

    if request.method == 'POST':
        entree.type = request.form.get('type', entree.type)
        entree.justifie = request.form.get('justifie', entree.justifie)
        entree.heure_seance = request.form.get('heure_seance', '').strip() or None
        entree.motif = request.form.get('motif', '').strip() or None
        entree.decision = request.form.get('decision', '').strip() or None
        entree.parents_informes = request.form.get('parents_informes', entree.parents_informes)
        entree.date = date_db(request.form.get('date'))
        entree.classe = entree.eleve.classe

        photo = request.files.get('photo_justificatif')
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            entree.photo_justificatif = filename

        db.session.commit()
        ecrire_historique(
            u, 'MODIFICATION',
            f"{u.nom_complet} a modifie une entree journal pour {entree.eleve.nom_complet}."
        )
        flash('Entree modifiee.', 'success')
        return redirect(url_for('journal'))

    return render_template(
        'journal.html', u=u, entree_a_modifier=entree,
        classes=CLASSES, types=TYPES_JOURNAL, oui_non=OUI_NON,
        motifs=MOTIFS_SUGGERES,
        recherche='', filtre_classe='', filtre_date_debut='',
        filtre_date_fin='', filtre_type='', filtre_justifie='',
        pagination=None, entrees=[], now=datetime.now()
    )


@app.route('/journal/<int:entree_id>/supprimer', methods=['POST'])
@login_required
def journal_supprimer(entree_id):
    u = utilisateur_courant()
    entree = Journal.query.get_or_404(entree_id)
    if not peut_modifier_journal(entree):
        flash('Vous ne pouvez supprimer que vos propres saisies.', 'danger')
        return redirect(url_for('journal'))

    nom_eleve = entree.eleve.nom_complet if entree.eleve else '?'
    type_e = entree.type
    db.session.delete(entree)
    db.session.commit()
    ecrire_historique(
        u, 'SUPPRESSION',
        f"{u.nom_complet} a supprime un {type_e} pour {nom_eleve}."
    )
    flash(f'{type_e} de {nom_eleve} supprime.', 'success')
    return redirect(url_for('journal'))


@app.route('/api/sync')
@login_required
def api_sync():
    last_journal = db.session.query(db.func.max(Journal.date_creation)).scalar()
    last_eleve = db.session.query(db.func.max(Eleve.id)).scalar()
    last = last_journal or datetime.utcnow()
    nb_convoquer = 0
    try:
        p = Parametre.get()
        for e in Eleve.query.filter_by(actif=True).all():
            if e.statut == 'À CONVOQUER':
                nb_convoquer += 1
    except Exception:
        pass
    return jsonify({
        'last_modified': last.isoformat() if last else None,
        'server_time': datetime.utcnow().isoformat(),
        'nb_convoquer': nb_convoquer,
    })


@app.route('/api/journal/partial')
@login_required
def api_journal_partial():
    page = request.args.get('page', 1, type=int)
    q = Journal.query.join(Eleve, Journal.eleve_id == Eleve.id).order_by(
        Journal.date.desc(), Journal.date_creation.desc()
    )
    pagination = q.paginate(page=page, per_page=50, error_out=False)
    rows = []
    for e in pagination.items:
        rows.append({
            'id': e.id,
            'date': fr_date(e.date),
            'classe': e.classe,
            'eleve': e.eleve.nom_complet if e.eleve else '?',
            'type': e.type,
            'heure': e.heure_seance or '-',
            'justifie': e.justifie,
            'motif': e.motif or '-',
            'decision': e.decision or '-',
            'parents': e.parents_informes,
            'saisi_par': e.saisi_par.nom_complet if e.saisi_par else '?',
            'date_creation': fr_datetime(e.date_creation),
            'photo': bool(e.photo_justificatif),
        })
    return jsonify({
        'rows': rows,
        'has_next': pagination.has_next,
        'page': pagination.page,
    })


@app.route('/api/offline_sync', methods=['POST'])
@login_required
def api_offline_sync():
    u = utilisateur_courant()
    donnees = request.get_json(silent=True) or []
    importe = 0
    for item in donnees:
        try:
            eleve_id = item.get('eleve_id')
            eleve = Eleve.query.get(eleve_id)
            if not eleve:
                continue
            entree = Journal(
                date=date_db(item.get('date')),
                classe=eleve.classe,
                eleve_id=eleve.id,
                type=item.get('type', 'Retard'),
                heure_seance=item.get('heure_seance'),
                justifie=item.get('justifie', 'Non'),
                motif=item.get('motif'),
                decision=item.get('decision'),
                parents_informes=item.get('parents_informes', 'Non'),
                saisi_par_id=u.id,
            )
            db.session.add(entree)
            importe += 1
        except Exception:
            continue
    db.session.commit()
    ecrire_historique(
        u, 'SYNCHRO HORS-LIGNE',
        f'{importe} entree(s) reintegree(s) depuis le mode hors-ligne.'
    )
    return jsonify({'importe': importe})


# ------------------------------------------------------------------
# Eleves
# ------------------------------------------------------------------
@app.route('/eleves')
@login_required
def eleves():
    u = utilisateur_courant()
    page = request.args.get('page', 1, type=int)
    recherche = request.args.get('recherche', '').strip()
    filtre_classe = request.args.get('classe', '').strip()
    filtre_statut = request.args.get('statut', '').strip()

    q = Eleve.query.filter_by(actif=True)
    if recherche:
        q = q.filter(
            (Eleve.nom.ilike(f'%{recherche}%')) |
            (Eleve.prenoms.ilike(f'%{recherche}%')) |
            (Eleve.nom_complet.ilike(f'%{recherche}%'))
        )
    if filtre_classe:
        q = q.filter_by(classe=filtre_classe)
    q = q.order_by(Eleve.classe, Eleve.nom, Eleve.prenoms)
    pagination = q.paginate(page=page, per_page=100, error_out=False)

    p = Parametre.get()
    eleves_donnees = []
    for e in pagination.items:
        eleves_donnees.append({
            'eleve': e,
            'retards': e.retards,
            'absences': e.absences,
            'absences_nj': e.absences_non_justifiees,
            'renvois': e.renvois,
            'statut': e.statut,
            'statut_couleur': e.statut_couleur,
        })

    classes_presentes = sorted({e.classe for e in Eleve.query.filter_by(actif=True).all()})

    return render_template(
        'eleves.html',
        u=u,
        eleves_donnees=eleves_donnees,
        pagination=pagination,
        classes=CLASSES,
        classes_presentes=classes_presentes,
        recherche=recherche,
        filtre_classe=filtre_classe,
        filtre_statut=filtre_statut,
        now=datetime.now()
    )


@app.route('/eleves/ajouter', methods=['POST'])
@login_required
def eleve_ajouter():
    u = utilisateur_courant()
    classe = request.form.get('classe', '').strip()
    prenoms = request.form.get('prenoms', '').strip()
    nom = request.form.get('nom', '').strip()
    if not classe or not prenoms or not nom:
        flash('Classe, prenoms et nom sont obligatoires.', 'danger')
        return redirect(url_for('eleves'))

    nom_complet = f"{nom.upper()} {prenoms.title()}"
    max_num = db.session.query(db.func.max(Eleve.numero)).filter_by(classe=classe).scalar() or 0
    e = Eleve(
        numero=max_num + 1, classe=classe, prenoms=prenoms,
        nom=nom.upper(), nom_complet=nom_complet
    )
    db.session.add(e)
    db.session.commit()
    ecrire_historique(
        u, 'AJOUT ELEVE',
        f"{u.nom_complet} a ajoute l'eleve {nom_complet} ({classe})."
    )
    flash(f'Eleve {nom_complet} ajoute.', 'success')
    return redirect(url_for('eleves'))


@app.route('/eleves/<int:eleve_id>/modifier', methods=['POST'])
@login_required
def eleve_modifier(eleve_id):
    u = utilisateur_courant()
    e = Eleve.query.get_or_404(eleve_id)
    e.classe = request.form.get('classe', e.classe).strip()
    e.nom = request.form.get('nom', e.nom).strip().upper()
    e.prenoms = request.form.get('prenoms', e.prenoms).strip().title()
    e.nom_complet = f"{e.nom} {e.prenoms}"
    db.session.commit()
    ecrire_historique(
        u, 'MODIFICATION ELEVE',
        f"{u.nom_complet} a modifie l'eleve #{e.id}."
    )
    flash('Eleve modifie.', 'success')
    return redirect(url_for('eleves'))


@app.route('/eleves/<int:eleve_id>/supprimer', methods=['POST'])
@login_required
def eleve_supprimer(eleve_id):
    u = utilisateur_courant()
    e = Eleve.query.get_or_404(eleve_id)
    nom = e.nom_complet
    db.session.delete(e)
    db.session.commit()
    ecrire_historique(
        u, 'SUPPRESSION ELEVE',
        f"{u.nom_complet} a supprime l'eleve {nom}."
    )
    flash(f'Eleve {nom} supprime.', 'success')
    return redirect(url_for('eleves'))


@app.route('/eleves/<int:eleve_id>/fiche')
@login_required
def eleve_fiche(eleve_id):
    u = utilisateur_courant()
    e = Eleve.query.get_or_404(eleve_id)
    entrees = Journal.query.filter_by(eleve_id=e.id).order_by(Journal.date.desc()).all()
    fiches = FicheRenvoi.query.filter_by(eleve_id=e.id).order_by(FicheRenvoi.date_renvoi.desc()).all()
    return render_template(
        'eleve_fiche.html',
        u=u, eleve=e, entrees=entrees, fiches=fiches,
        retards=e.retards, absences=e.absences,
        absences_nj=e.absences_non_justifiees, renvois=e.renvois,
        statut=e.statut, statut_couleur=e.statut_couleur,
        now=datetime.now()
    )


@app.route('/eleves/import', methods=['POST'])
@login_required
def eleves_import():
    if not HAS_OPENPYXL:
        flash('openpyxl non installe.', 'danger')
        return redirect(url_for('eleves'))

    fichier = request.files.get('fichier_excel')
    if not fichier or fichier.filename == '':
        flash('Veuillez selectionner un fichier Excel.', 'danger')
        return redirect(url_for('eleves'))

    try:
        wb = openpyxl.load_workbook(fichier, data_only=True)
    except Exception as exc:
        flash(f'Erreur lecture fichier : {exc}', 'danger')
        return redirect(url_for('eleves'))

    feuille = None
    for nom_feuille in wb.sheetnames:
        if 'lève' in nom_feuille.lower() or 'eleve' in nom_feuille.lower():
            feuille = wb[nom_feuille]
            break
    if feuille is None:
        feuille = wb.active

    lignes = list(feuille.iter_rows(values_only=True))
    indice_debut = 0
    for i, row in enumerate(lignes):
        if row and any(str(c).strip().lower() in ('classe', 'n°', 'numero') for c in row if c):
            indice_debut = i + 1
            break

    ajoutes = 0
    ignores = 0
    for row in lignes[indice_debut:]:
        if not row or all(c is None for c in row):
            continue
        classe = str(row[1]).strip() if len(row) > 1 and row[1] else ''
        prenoms = str(row[2]).strip() if len(row) > 2 and row[2] else ''
        nom = str(row[3]).strip() if len(row) > 3 and row[3] else ''
        if not classe or not prenoms or not nom:
            continue
        existe = Eleve.query.filter_by(
            nom=nom.upper(), prenoms=prenoms.title(), classe=classe
        ).first()
        if existe:
            ignores += 1
            continue
        max_num = db.session.query(db.func.max(Eleve.numero)).filter_by(classe=classe).scalar() or 0
        nom_complet = f"{nom.upper()} {prenoms.title()}"
        e = Eleve(
            numero=max_num + 1, classe=classe, prenoms=prenoms,
            nom=nom.upper(), nom_complet=nom_complet
        )
        db.session.add(e)
        ajoutes += 1

    db.session.commit()
    u = utilisateur_courant()
    ecrire_historique(
        u, 'IMPORT EXCEL',
        f'Import eleve : {ajoutes} ajoute(s), {ignores} doublon(s) ignore(s).'
    )
    flash(f'Import termine : {ajoutes} eleve(s) ajoute(s), {ignores} doublon(s) ignore(s).', 'success')
    return redirect(url_for('eleves'))


# ------------------------------------------------------------------
# Synthèse
# ------------------------------------------------------------------
@app.route('/synthese')
@login_required
def synthese():
    u = utilisateur_courant()
    periode = request.args.get('periode', 'annee').strip()

    aujourd_hui = datetime.utcnow().date()
    if periode == 'aujourdhui':
        date_min = datetime.combine(aujourd_hui, datetime.min.time())
    elif periode == 'semaine':
        date_min = datetime.combine(aujourd_hui - timedelta(days=7), datetime.min.time())
    elif periode == 'mois':
        date_min = datetime.combine(aujourd_hui - timedelta(days=30), datetime.min.time())
    else:
        date_min = datetime(2000, 1, 1)

    p = Parametre.get()
    synthese_donnees = []
    totaux = {'effectif': 0, 'retards': 0, 'absences': 0, 'absences_nj': 0, 'renvois': 0,
              'convoquer': 0, 'surveiller': 0}

    for cl in CLASSES:
        eleves_classe = Eleve.query.filter_by(classe=cl, actif=True).all()
        effectif = len(eleves_classe)
        r = a = anj = rn = c = s = 0
        for e in eleves_classe:
            r += e.journal_entries.filter(Journal.type == 'Retard', Journal.date >= date_min).count()
            a += e.journal_entries.filter(Journal.type == 'Absence', Journal.date >= date_min).count()
            anj += e.journal_entries.filter(
                Journal.type == 'Absence', Journal.justifie == 'Non', Journal.date >= date_min
            ).count()
            rn += e.journal_entries.filter(Journal.type == 'Renvoi', Journal.date >= date_min).count()
            if e.statut == 'À CONVOQUER':
                c += 1
            elif e.statut == 'À SURVEILLER':
                s += 1
        synthese_donnees.append({
            'classe': cl, 'effectif': effectif, 'retards': r, 'absences': a,
            'absences_nj': anj, 'renvois': rn, 'convoquer': c, 'surveiller': s,
        })
        totaux['effectif'] += effectif
        totaux['retards'] += r
        totaux['absences'] += a
        totaux['absences_nj'] += anj
        totaux['renvois'] += rn
        totaux['convoquer'] += c
        totaux['surveiller'] += s

    return render_template(
        'synthese.html',
        u=u, synthese=synthese_donnees, totaux=totaux,
        periode=periode, classes=CLASSES,
        chart_labels=[s['classe'] for s in synthese_donnees],
        chart_retards=[s['retards'] for s in synthese_donnees],
        chart_absences=[s['absences'] for s in synthese_donnees],
        chart_renvois=[s['renvois'] for s in synthese_donnees],
        now=datetime.now()
    )


# ------------------------------------------------------------------
# Fiche de renvoi
# ------------------------------------------------------------------
@app.route('/fiche_renvoi')
@login_required
def fiche_renvoi():
    u = utilisateur_courant()
    page = request.args.get('page', 1, type=int)
    recherche = request.args.get('recherche', '').strip()
    q = FicheRenvoi.query.join(Eleve).order_by(FicheRenvoi.date_renvoi.desc())
    if recherche:
        q = q.filter(
            (Eleve.nom.ilike(f'%{recherche}%')) |
            (Eleve.prenoms.ilike(f'%{recherche}%'))
        )
    pagination = q.paginate(page=page, per_page=50, error_out=False)

    eleves_par_classe = {}
    for e in Eleve.query.filter_by(actif=True).all():
        eleves_par_classe.setdefault(e.classe, []).append({'id': e.id, 'nom_complet': e.nom_complet, 'numero': e.numero})
    import json as _json
    eleves_json = _json.dumps(eleves_par_classe, ensure_ascii=False)

    return render_template(
        'fiche_renvoi.html',
        u=u, fiches=pagination.items, pagination=pagination,
        recherche=recherche, classes=CLASSES, eleves_json=eleves_json, now=datetime.now()
    )


@app.route('/fiche_renvoi/generer', methods=['POST'])
@login_required
def fiche_generer():
    u = utilisateur_courant()
    eleve_id = request.form.get('eleve_id', type=int)
    motif = request.form.get('motif', '').strip()
    duree = request.form.get('duree', '1 jour').strip()
    date_renvoi = date_db(request.form.get('date_renvoi'))
    retour = request.form.get('retour_en_classe_le')
    date_retour = date_db(retour) if retour else None

    if not eleve_id or not motif:
        flash('Eleve et motif sont obligatoires.', 'danger')
        return redirect(url_for('fiche_renvoi'))

    eleve = Eleve.query.get(eleve_id)
    if eleve is None:
        flash('Eleve introuvable.', 'danger')
        return redirect(url_for('fiche_renvoi'))

    fiche = FicheRenvoi(
        eleve_id=eleve.id, date_renvoi=date_renvoi, motif=motif,
        duree=duree, retour_en_classe_le=date_retour, cree_par_id=u.id
    )
    db.session.add(fiche)
    db.session.commit()
    ecrire_historique(
        u, 'AJOUT FICHE',
        f"{u.nom_complet} a genere une fiche de renvoi pour {eleve.nom_complet} ({duree})."
    )
    flash(f'Fiche de renvoi generee pour {eleve.nom_complet}.', 'success')
    return redirect(url_for('fiche_renvoi'))


@app.route('/fiche_renvoi/<int:fiche_id>')
@login_required
def fiche_voir(fiche_id):
    u = utilisateur_courant()
    fiche = FicheRenvoi.query.get_or_404(fiche_id)
    e = fiche.eleve
    return render_template(
        'fiche_voir.html',
        u=u, fiche=fiche, eleve=e,
        retards=e.retards, absences=e.absences,
        absences_nj=e.absences_non_justifiees, renvois=e.renvois,
        now=datetime.now()
    )


@app.route('/fiche_renvoi/<int:fiche_id>/supprimer', methods=['POST'])
@login_required
def fiche_supprimer(fiche_id):
    u = utilisateur_courant()
    fiche = FicheRenvoi.query.get_or_404(fiche_id)
    db.session.delete(fiche)
    db.session.commit()
    flash('Fiche de renvoi supprimee.', 'success')
    return redirect(url_for('fiche_renvoi'))


@app.route('/fiche_renvoi/<int:fiche_id>/pdf')
@login_required
def fiche_pdf(fiche_id):
    if not HAS_REPORTLAB:
        flash('reportlab non installe.', 'danger')
        return redirect(url_for('fiche_voir', fiche_id=fiche_id))
    fiche = FicheRenvoi.query.get_or_404(fiche_id)
    e = fiche.eleve
    p = Parametre.get()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    titre = ParagraphStyle('titre', parent=styles['Title'],
                           fontName='Helvetica-Bold', fontSize=16,
                           textColor=colors.HexColor('#0B2C4A'), alignment=1)
    sous = ParagraphStyle('sous', parent=styles['Normal'],
                          fontSize=11, alignment=1, textColor=colors.HexColor('#0B2C4A'))
    normal = styles['Normal']

    elems = []
    elems.append(Paragraph(p.nom_ecole.upper(), titre))
    elems.append(Paragraph(f"FICHE DE RENVOI - Annee scolaire {p.annee_scolaire}", sous))
    elems.append(Spacer(1, 12))

    data = [
        ['Classe :', e.classe],
        ['Eleve :', e.nom_complet],
        ['Date du renvoi :', fr_date(fiche.date_renvoi)],
        ['Motif :', fiche.motif],
        ['Duree :', fiche.duree],
        ['Retour en classe le :', fr_date(fiche.retour_en_classe_le) if fiche.retour_en_classe_le else 'A definir'],
    ]
    tbl = Table(data, colWidths=[45*mm, 120*mm])
    tbl.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.grey),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1, 16))

    elems.append(Paragraph('Cumul disciplinaire (depuis le Journal) :', styles['Heading3']))
    data2 = [
        ['Retards cumules', str(e.retards)],
        ['Absences cumulees', str(e.absences)],
        ['Absences non justifiees', str(e.absences_non_justifiees)],
        ['Renvois cumules (y compris celui-ci)', str(e.renvois + 1)],
    ]
    tbl2 = Table(data2, colWidths=[130*mm, 35*mm])
    tbl2.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F5F5')),
    ]))
    elems.append(tbl2)
    elems.append(Spacer(1, 30))

    elems.append(Paragraph('Signatures :', styles['Heading3']))
    sig_data = [
        ['Surveillant : ____________________', 'Parent : ____________________', 'Surveillant General : ____________________'],
        ['Date : ____________', 'Date : ____________', 'Date : ____________'],
    ]
    tbl3 = Table(sig_data, colWidths=[60*mm, 60*mm, 60*mm])
    tbl3.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 20),
    ]))
    elems.append(tbl3)

    doc.build(elems)
    buffer.seek(0)
    nom_fichier = f"fiche_renvoi_{e.nom}_{e.prenoms}_{fiche.id}.pdf"
    return send_file(
        buffer, mimetype='application/pdf',
        as_attachment=True, download_name=nom_fichier
    )


# ------------------------------------------------------------------
# Paramètres (Surveillant Général uniquement)
# ------------------------------------------------------------------
@app.route('/parametres', methods=['GET', 'POST'])
@login_required
@role_required('surveillant_general')
def parametres():
    u = utilisateur_courant()
    p = Parametre.get()
    if request.method == 'POST':
        try:
            p.seuil_retard = int(request.form.get('seuil_retard', 3))
            p.seuil_absence_non_justifiee = int(request.form.get('seuil_absence_non_justifiee', 3))
            p.seuil_renvoi = int(request.form.get('seuil_renvoi', 1))
            p.annee_scolaire = request.form.get('annee_scolaire', p.annee_scolaire).strip()
            p.nom_ecole = request.form.get('nom_ecole', p.nom_ecole).strip()
            db.session.commit()
            ecrire_historique(
                u, 'MODIFICATION PARAMETRES',
                f"{u.nom_complet} a modifie les paramètres (seuils : {p.seuil_retard}, {p.seuil_absence_non_justifiee}, {p.seuil_renvoi})."
            )
            flash('Paramètres mis à jour. Les statuts se recalculent automatiquement.', 'success')
        except Exception as exc:
            db.session.rollback()
            flash(f'Erreur : {exc}', 'danger')
        return redirect(url_for('parametres'))
    return render_template('parametres.html', u=u, p=p, now=datetime.now())


# ------------------------------------------------------------------
# Utilisateurs (Surveillant Général uniquement)
# ------------------------------------------------------------------
@app.route('/utilisateurs')
@login_required
@role_required('surveillant_general')
def utilisateurs():
    u = utilisateur_courant()
    liste = Utilisateur.query.order_by(Utilisateur.role, Utilisateur.nom_complet).all()
    return render_template('utilisateurs.html', u=u, liste=liste,
                           roles=ROLES, now=datetime.now())


@app.route('/utilisateurs/ajouter', methods=['POST'])
@login_required
@role_required('surveillant_general')
def utilisateur_ajouter():
    u = utilisateur_courant()
    nom_complet = request.form.get('nom_complet', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    role = request.form.get('role', 'surveillant')
    telephone = request.form.get('telephone', '').strip()

    if not nom_complet or not email or not password:
        flash('Nom complet, email et mot de passe sont obligatoires.', 'danger')
        return redirect(url_for('utilisateurs'))
    if Utilisateur.query.filter_by(email=email).first():
        flash('Cet email existe déjà.', 'danger')
        return redirect(url_for('utilisateurs'))

    nouvel = Utilisateur(
        nom_complet=nom_complet, email=email, role=role,
        telephone=telephone, actif=True
    )
    nouvel.set_password(password)
    db.session.add(nouvel)
    db.session.commit()
    ecrire_historique(
        u, 'AJOUT UTILISATEUR',
        f"{u.nom_complet} a cree le compte {email} ({role})."
    )
    flash(f'Utilisateur {email} cree.', 'success')
    return redirect(url_for('utilisateurs'))


@app.route('/utilisateurs/<int:user_id>/modifier', methods=['POST'])
@login_required
@role_required('surveillant_general')
def utilisateur_modifier(user_id):
    u = utilisateur_courant()
    user = Utilisateur.query.get_or_404(user_id)
    user.role = request.form.get('role', user.role)
    user.telephone = request.form.get('telephone', user.telephone).strip()
    nouveau_mdp = request.form.get('password', '').strip()
    if nouveau_mdp:
        user.set_password(nouveau_mdp)
    user.actif = bool(request.form.get('actif'))
    db.session.commit()
    ecrire_historique(
        u, 'MODIFICATION UTILISATEUR',
        f"{u.nom_complet} a modifie le compte {user.email}."
    )
    flash(f'Utilisateur {user.email} modifie.', 'success')
    return redirect(url_for('utilisateurs'))


@app.route('/utilisateurs/<int:user_id>/supprimer', methods=['POST'])
@login_required
@role_required('surveillant_general')
def utilisateur_supprimer(user_id):
    u = utilisateur_courant()
    if user_id == u.id:
        flash('Vous ne pouvez pas supprimer votre propre compte.', 'danger')
        return redirect(url_for('utilisateurs'))
    user = Utilisateur.query.get_or_404(user_id)
    nom = user.email
    db.session.delete(user)
    db.session.commit()
    ecrire_historique(
        u, 'SUPPRESSION UTILISATEUR',
        f"{u.nom_complet} a supprime le compte {nom}."
    )
    flash(f'Utilisateur {nom} supprime.', 'success')
    return redirect(url_for('utilisateurs'))


# ------------------------------------------------------------------
# Historique / audit
# ------------------------------------------------------------------
@app.route('/historique')
@login_required
def historique():
    u = utilisateur_courant()
    page = request.args.get('page', 1, type=int)
    filtre_user = request.args.get('utilisateur', '').strip()
    filtre_action = request.args.get('action', '').strip()
    filtre_date = request.args.get('date', '').strip()

    q = HistoriqueAction.query.join(Utilisateur, isouter=True).order_by(
        HistoriqueAction.date_action.desc()
    )
    if filtre_user:
        q = q.filter(Utilisateur.nom_complet.ilike(f'%{filtre_user}%'))
    if filtre_action:
        q = q.filter(HistoriqueAction.action.ilike(f'%{filtre_action}%'))
    if filtre_date:
        try:
            d = datetime.strptime(filtre_date, '%Y-%m-%d')
            q = q.filter(db.func.date(HistoriqueAction.date_action) == d.date())
        except ValueError:
            pass

    pagination = q.paginate(page=page, per_page=50, error_out=False)
    return render_template(
        'historique.html',
        u=u, historique=pagination.items, pagination=pagination,
        filtre_user=filtre_user, filtre_action=filtre_action,
        filtre_date=filtre_date, now=datetime.now()
    )


# ------------------------------------------------------------------
# Exports
# ------------------------------------------------------------------
@app.route('/journal/exporter/excel')
@login_required
def journal_exporter_excel():
    if not HAS_OPENPYXL:
        flash('openpyxl non installe.', 'danger')
        return redirect(url_for('journal'))
    u = utilisateur_courant()
    entrees = Journal.query.join(Eleve).order_by(Journal.date.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Journal'
    entetes = ['Date', 'Classe', 'Eleve', 'Type', 'Heure / seance',
               'Justifie', 'Motif', 'Decision', 'Parents informes', 'Saisi par']
    ws.append(entetes)
    for e in entrees:
        ws.append([
            fr_date(e.date), e.classe, e.eleve.nom_complet if e.eleve else '?',
            e.type, e.heure_seance or '-', e.justifie, e.motif or '-',
            e.decision or '-', e.parents_informes,
            e.saisi_par.nom_complet if e.saisi_par else '?'
        ])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    ecrire_historique(u, 'EXPORT EXCEL', f'{u.nom_complet} a exporte le journal en Excel.')
    return send_file(
        buffer, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'journal_discipline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@app.route('/journal/exporter/pdf')
@login_required
def journal_exporter_pdf():
    if not HAS_REPORTLAB:
        flash('reportlab non installe.', 'danger')
        return redirect(url_for('journal'))
    u = utilisateur_courant()
    entrees = Journal.query.join(Eleve).order_by(Journal.date.desc()).all()
    p = Parametre.get()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    titre = ParagraphStyle('titre', parent=styles['Title'],
                           fontName='Helvetica-Bold', fontSize=14,
                           textColor=colors.HexColor('#0B2C4A'), alignment=1)
    elems = []
    elems.append(Paragraph(p.nom_ecole.upper(), titre))
    elems.append(Paragraph(f"Journal des retards, absences et renvois - {p.annee_scolaire}", styles['Normal']))
    elems.append(Paragraph(f"Exporte le {fr_datetime(datetime.now())} par {u.nom_complet}", styles['Normal']))
    elems.append(Spacer(1, 10))

    data = [['Date', 'Classe', 'Eleve', 'Type', 'Heure', 'Just.', 'Motif', 'Decision', 'Parents', 'Saisi par']]
    for e in entrees:
        data.append([
            fr_date(e.date), e.classe, (e.eleve.nom_complet if e.eleve else '?')[:25],
            e.type, (e.heure_seance or '-')[:10], e.justifie,
            (e.motif or '-')[:25], (e.decision or '-')[:20],
            e.parents_informes, (e.saisi_par.nom_complet if e.saisi_par else '?')[:20]
        ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0B2C4A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF2F7')]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buffer.seek(0)
    ecrire_historique(u, 'EXPORT PDF', f'{u.nom_complet} a exporte le journal en PDF.')
    return send_file(
        buffer, mimetype='application/pdf',
        as_attachment=True,
        download_name=f'journal_discipline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    )


@app.route('/synthese/exporter/pdf')
@login_required
def synthese_exporter_pdf():
    if not HAS_REPORTLAB:
        flash('reportlab non installe.', 'danger')
        return redirect(url_for('synthese'))
    u = utilisateur_courant()
    p = Parametre.get()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    titre = ParagraphStyle('titre', parent=styles['Title'],
                           fontName='Helvetica-Bold', fontSize=14,
                           textColor=colors.HexColor('#0B2C4A'), alignment=1)
    elems = []
    elems.append(Paragraph(p.nom_ecole.upper(), titre))
    elems.append(Paragraph(f"Synthese disciplinaire par classe - {p.annee_scolaire}", styles['Normal']))
    elems.append(Spacer(1, 10))

    data = [['Classe', 'Effectif', 'Retards', 'Absences', 'Abs. non just.', 'Renvois', 'A convoquer', 'A surveiller']]
    for s in synthese_donnees_local():
        data.append([s['classe'], str(s['effectif']), str(s['retards']), str(s['absences']),
                     str(s['absences_nj']), str(s['renvois']), str(s['convoquer']), str(s['surveiller'])])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0B2C4A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF2F7')]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buffer.seek(0)
    return send_file(
        buffer, mimetype='application/pdf',
        as_attachment=True,
        download_name=f'synthese_{p.annee_scolaire}.pdf'
    )


def synthese_donnees_local():
    res = []
    for cl in CLASSES:
        eleves_classe = Eleve.query.filter_by(classe=cl, actif=True).all()
        effectif = len(eleves_classe)
        r = a = anj = rn = c = s = 0
        for e in eleves_classe:
            r += e.journal_entries.filter_by(type='Retard').count()
            a += e.journal_entries.filter_by(type='Absence').count()
            anj += e.journal_entries.filter_by(type='Absence', justifie='Non').count()
            rn += e.journal_entries.filter_by(type='Renvoi').count()
            if e.statut == 'À CONVOQUER':
                c += 1
            elif e.statut == 'À SURVEILLER':
                s += 1
        res.append({'classe': cl, 'effectif': effectif, 'retards': r, 'absences': a,
                    'absences_nj': anj, 'renvois': rn, 'convoquer': c, 'surveiller': s})
    return res


# ------------------------------------------------------------------
# Sauvegarde base
# ------------------------------------------------------------------
@app.route('/backup')
@login_required
def backup():
    u = utilisateur_courant()
    chemin_db = os.path.join(app.instance_path, 'don_bosco.db')
    if not os.path.exists(chemin_db):
        flash('Base de donnees introuvable.', 'danger')
        return redirect(url_for('dashboard'))
    ecrire_historique(
        u, 'SAUVEGARDE', f'{u.nom_complet} a telecharge une sauvegarde de la base de donnees.'
    )
    return send_file(
        chemin_db, as_attachment=True,
        download_name=f'don_bosco_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    )


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': 'Don Bosco Gestion Discipline 2026-2027'})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
