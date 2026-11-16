// -*- coding: utf-8 -*-
// main.js - Don Bosco - Gestion Discipline 2026-2027
// Synchronisation, hors-ligne, formulaires, icônes Lucide

const API_SYNC = '/api/sync';
const API_OFFLINE = '/api/offline_sync';

let derniereSynchro = null;
let formulaireActif = false;
let horsLigne = false;
let fileAttenteHorsLigne = JSON.parse(localStorage.getItem('db_offline_queue') || '[]');

const indicateurSynchro = document.getElementById('indicateur-synchro');
const texteSynchro = document.getElementById('texte-synchro');
const alerteHorsLigne = document.getElementById('alerte-hors-ligne');

// Détection hors-ligne
function mettreAJourStatutConnexion() {
  const enLigne = navigator.onLine;
  if (horsLigne === enLigne) return;
  horsLigne = !enLigne;
  if (alerteHorsLigne) {
    alerteHorsLigne.style.display = enLigne ? 'none' : 'block';
  }
  if (enLigne && fileAttenteHorsLigne.length > 0) {
    synchroniserHorsLigne();
  }
}
window.addEventListener('online', mettreAJourStatutConnexion);
window.addEventListener('offline', mettreAJourStatutConnexion);
mettreAJourStatutConnexion();

// Synchronisation hors-ligne
async function synchroniserHorsLigne() {
  try {
    const reponse = await fetch(API_OFFLINE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fileAttenteHorsLigne),
    });
    const resultat = await reponse.json();
    if (resultat.importe > 0) {
      fileAttenteHorsLigne = [];
      localStorage.removeItem('db_offline_queue');
      if (typeof rechargerJournal === 'function') rechargerJournal();
      if (typeof rechargerEleves === 'function') rechargerEleves();
    }
  } catch (e) {
    console.warn('Echec synchro hors-ligne', e);
  }
}

// Polling de synchronisation (toutes les 5 secondes)
async function verifierSynchro() {
  try {
    const reponse = await fetch(API_SYNC);
    const donnees = await reponse.json();
    const maintenant = new Date(donnees.server_time).toLocaleTimeString('fr-FR', { hour12: false });

    if (indicateurSynchro) {
      indicateurSynchro.className = 'dot';
      indicateurSynchro.title = 'Synchronisé';
    }
    if (texteSynchro) {
      texteSynchro.textContent = 'Synchronisé - Dernière mise à jour : ' + maintenant;
    }
    derniereSynchro = donnees.last_modified;

    const badge = document.getElementById('badge-convoquer');
    if (badge) {
      if (donnees.nb_convoquer > 0) {
        badge.textContent = donnees.nb_convoquer;
        badge.style.display = 'inline-flex';
      } else {
        badge.style.display = 'none';
      }
    }

    if (!formulaireActif && donnees.last_modified) {
      const ancien = sessionStorage.getItem('db_last_sync');
      if (ancien && ancien !== donnees.last_modified) {
        if (typeof rafraichirApresSynchro === 'function') rafraichirApresSynchro();
      }
    }
    sessionStorage.setItem('db_last_sync', donnees.last_modified || '');
  } catch (e) {
    console.warn('Polling synchro échoué', e);
  }
}

// Re-render des icônes Lucide après modification du DOM
function rafraichirIcones() {
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

// Filtrage élèves par classe (formulaire journal)
function configurerFiltreEleve(selectClasseId, inputRechercheId, hiddenId, datalistId) {
  const selClasse = document.getElementById(selectClasseId);
  const inputRecherche = document.getElementById(inputRechercheId);
  const datalist = document.getElementById(datalistId);
  const inputId = document.getElementById(hiddenId);
  if (!selClasse || !inputRecherche || !datalist || !inputId) return;

  let donneesEleves = {};
  try {
    donneesEleves = JSON.parse(datalist.getAttribute('data-eleves') || '{}');
  } catch (e) {}

  function filtrer() {
    const classe = selClasse.value;
    const terme = inputRecherche.value.toLowerCase();
    datalist.innerHTML = '';
    inputId.value = '';
    (donneesEleves[classe] || []).forEach(e => {
      const nom = (e.nom_complet || '').toLowerCase();
      if (!terme || nom.includes(terme)) {
        const opt = document.createElement('option');
        opt.value = e.nom_complet;
        opt.dataset.id = e.id;
        datalist.appendChild(opt);
      }
    });
  }
  selClasse.addEventListener('change', filtrer);
  inputRecherche.addEventListener('input', filtrer);
  inputRecherche.addEventListener('change', () => {
    for (let o of datalist.options) {
      if (o.value === inputRecherche.value) { inputId.value = o.dataset.id; break; }
    }
  });
  filtrer();
}

// Suivi formulaire actif
function marquerFormulaireActif(actif) {
  formulaireActif = actif;
}
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('focusin', () => marquerFormulaireActif(true));
  form.addEventListener('focusout', () => marquerFormulaireActif(false));
});

// Suppression avec confirmation
function confirmerSuppression(message, url) {
  if (confirm(message)) {
    const f = document.createElement('form');
    f.method = 'POST';
    f.action = url;
    document.body.appendChild(f);
    f.submit();
  }
}

// WhatsApp
function envoyerWhatsApp(nom, date, heure, motif) {
  const texte = 'Bonjour, votre enfant ' + nom + ' a eu un retard/absence le ' + date + ' à ' + heure + '. Motif : ' + motif + '. Merci de signer la fiche. Collège Don Bosco.';
  const url = 'https://wa.me/?text=' + encodeURIComponent(texte);
  window.open(url, '_blank');
}

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
  rafraichirIcones();

  const pagesSync = ['/dashboard', '/journal', '/eleves'];
  const surPageSync = pagesSync.some(p => window.location.pathname.includes(p));
  if (surPageSync) {
    verifierSynchro();
    setInterval(verifierSynchro, 5000);
  }

  document.querySelectorAll('[data-confirmer]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const msg = btn.getAttribute('data-message') || 'Confirmer la suppression ?';
      const url = btn.getAttribute('data-url');
      confirmerSuppression(msg, url);
    });
  });

  document.querySelectorAll('.btn-whatsapp').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      envoyerWhatsApp(
        btn.dataset.nom || '',
        btn.dataset.date || '',
        btn.dataset.heure || '',
        btn.dataset.motif || ''
      );
    });
  });
});

// Fonctions exposées
window.rechargerJournal = function() { location.reload(); };
window.rechargerEleves = function() { location.reload(); };
window.rafraichirApresSynchro = function() {
  if (window.location.pathname.includes('/journal')) location.reload();
};
