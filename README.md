# grm-backend

Backend Django du **GRM (Grievance Redress Mechanism / Mécanisme de Gestion des Plaintes — MGP)**,
la plateforme qui permet d'enregistrer les plaintes des communautés, de les suivre jusqu'à leur
résolution, et de les rattacher à un découpage administratif (village, canton, préfecture, région).

Le backend expose :
- une **application web d'administration/suivi** (Django templates, `dashboard/`) pour les agents,
  coordinateurs, ministres, etc. ;
- une **API REST** consommée par l'application mobile (`grm-frontend`, React Native +
  WatermelonDB) pour la saisie terrain hors-ligne ;
- une **API de service** consommée par les deux autres plateformes de l'écosystème (`CDD` et
  `MIS/SIG`), pour partager référentiels, facilitateurs (ADL) et plaintes sans que ces plateformes
  aient besoin d'accéder directement à CouchDB.

## Sommaire

- [Écosystème applicatif](#écosystème-applicatif)
- [Architecture](#architecture)
- [Modèle de données](#modèle-de-données)
- [Applications Django](#applications-django)
- [API](#api)
- [Stack technique](#stack-technique)
- [Installation](#installation)
- [Configuration (variables d'environnement)](#configuration-variables-denvironnement)
- [Lancer le projet](#lancer-le-projet)
- [Tests](#tests)
- [Permissions / groupes](#permissions--groupes)
- [Migration CouchDB → PostgreSQL](#migration-couchdb--postgresql)

---

## Écosystème applicatif

`grm-backend` est l'une de trois plateformes qui communiquent entre elles :

| Plateforme | Rôle | Port | Base de données |
|---|---|---|---|
| **DCC** (`cdd-backend` + `cdd-frontend`) | Collecte des communautaires, planification et suivi des sous-projets (mobile + web) | `:8001` | MySQL `cdd` |
| **GRM / MGP** (ce dépôt + `grm-frontend`) | Enregistrement et suivi des plaintes jusqu'à résolution | `:8002` | PostgreSQL `grm_db` (+ MySQL `mis` en lecture pour le référentiel administratif) |
| **SIG / MIS** (`cosomis`) | Suivi à distance des sous-projets et des données financières | `:8000` | MySQL `mis` |

Historiquement, ces trois plateformes échangeaient des données via des bases **CouchDB**
partagées (`grm`, `eadls`, `administrative_levels`, `grm_attachments`, `adb`). Le GRM est en
cours de migration vers PostgreSQL ; les autres plateformes basculent progressivement vers
l'**API de service** (`api/service/`, voir [service_api](#api)) exposée par ce backend plutôt que
de lire CouchDB directement. Le détail de cette migration (mapping de données, protocole de
synchronisation, scripts) est documenté dans [`CLAUDE.md`](./CLAUDE.md).

## Architecture

```
                        ┌───────────────────────────┐
                        │   grm-frontend (mobile)    │
                        │   React Native +           │
                        │   WatermelonDB (SQLite)    │
                        └─────────────┬─────────────┘
                                      │ REST (JWT) — pull/push sync, upload pièces jointes
                                      ▼
┌────────────────────────────────────────────────────────────────────┐
│                          grm-backend (Django)                       │
│                                                                      │
│  dashboard/        interface web (agents, coordinateurs, ministres) │
│  issue/            modèle métier : plaintes, statuts, commentaires  │
│  sync/             protocole de sync WatermelonDB (pull/push/files) │
│  attachments/       pièces jointes historiques (legacy CouchDB)      │
│  authentication/    utilisateurs, rôles, groupes de permissions     │
│  administrativelevels/  accès en lecture au référentiel `mis`       │
│  privacy/           gestion de la confidentialité des plaintes       │
│  budgeting/          rattachement budgétaire                        │
│  service_api/       API inter-plateformes (CDD, MIS) — remplace      │
│                      l'accès direct des autres apps à CouchDB       │
└───────────────┬───────────────────────────────────┬────────────────┘
                │                                    │
                ▼                                    ▼
     ┌─────────────────────┐               ┌──────────────────────┐
     │  PostgreSQL grm_db   │               │  MySQL mis (lecture)  │
     │  (source de vérité   │               │  référentiel des      │
     │  des plaintes)        │               │  découpages           │
     │                       │               │  administratifs        │
     └─────────────────────┘               │  (géré par `cosomis`)  │
                                             └──────────────────────┘
                ▲                                    ▲
                │ api/service/ (clé partagée)         │ lecture directe
     ┌─────────────────────┐               ┌──────────────────────┐
     │   cdd-backend        │               │   cosomis (SIG/MIS)   │
     └─────────────────────┘               └──────────────────────┘
```

Deux flux distincts vers le mobile, volontairement séparés :

1. **Flux de données** (`api/sync/pull/`, `api/sync/push/`) : uniquement des enregistrements
   légers (texte, nombres, booléens, dates, clés étrangères), au format du protocole de sync
   WatermelonDB.
2. **Flux de fichiers** (`api/attachments/`) : upload/download HTTP classique pour les pièces
   jointes (photos, audio, PDF), piloté par une file d'attente locale côté mobile.

Le référentiel des découpages administratifs (villages, cantons, préfectures, régions) n'est
**pas** dupliqué dans PostgreSQL : l'app `administrativelevels` route ses lectures/écritures vers
la base MySQL `mis` via un `DATABASE_ROUTERS` dédié (`grm.routers.MisRouter`), `mis` restant la
source de vérité gérée par le projet `cosomis`.

## Modèle de données

Autour de l'entité centrale **`Issue`** (la plainte) :

- `IssueStatus`, `IssueCategory`, `IssueDepartment`, `IssueAgeGroup`, `IssueType`,
  `IssueCitizenGroup1/2` — référentiels de qualification d'une plainte.
- `Comment`, `IssueStatusStory` — historique des échanges et des changements de statut.
- `Reason`, `EscalationReason`, `EscalationLevel` — motifs de rejet/résolution et escalade.
- `Attachment` — pièces jointes (photo, audio, PDF) liées à une plainte.
- `Adl` — les facilitateurs/représentants (Agent de Développement Local) et leur périmètre de
  villages gérés.
- `Wave` — vagues/campagnes de collecte.

Côté utilisateurs, `authentication.User` (modèle custom, `AUTH_USER_MODEL`) porte les rôles et
groupes de permissions (voir [Permissions / groupes](#permissions--groupes)).

Tous les modèles synchronisables héritent d'une base commune (`TimestampedSyncModel`) portant
`id` (UUID), `created_at`, `updated_at` et `is_deleted` (suppression logique / tombstone),
nécessaires au protocole de synchronisation offline-first.

## Applications Django

| App | Rôle |
|---|---|
| `grm` | Projet Django (settings, urls, routeur multi-base, tâches Celery communes) |
| `dashboard` | Interface web (authentification web, diagnostics, cartographie, suivi des plaintes, budget participatif, proxy CouchDB, logs) |
| `issue` | Modèles métier des plaintes et API classique associée |
| `sync` | Protocole de synchronisation WatermelonDB (`pull`/`push`), upload/suppression de pièces jointes mobiles, référentiel administratif pour le mobile, détection des appareils inactifs |
| `attachments` | Gestion historique des pièces jointes (héritée du flux CouchDB) |
| `authentication` | Utilisateurs, rôles, groupes de permissions, API d'authentification |
| `administrativelevels` | Accès en lecture (non managé) au référentiel administratif de la base `mis` |
| `privacy` | Règles de confidentialité applicables aux plaintes |
| `budgeting` | Rattachement des plaintes/actions à un budget |
| `service_api` | API inter-plateformes consommée par `cdd-backend` et `cosomis` (ADL, plaintes, référentiels), authentifiée par la clé partagée `GRM_SECRET_KEY_GENRATE` |

## API

- **Authentification JWT** : `POST /api/auth/token/`, `POST /api/auth/token/refresh/`,
  `POST /api/auth/token/blacklist/` (`djangorestframework-simplejwt`).
- **Synchronisation mobile (WatermelonDB)** :
  - `GET /api/sync/pull/` — changements depuis `last_pulled_at`, paginé (`has_more`/`cursor`),
    avec re-synchronisation complète forcée au-delà de `TOMBSTONE_MAX_AGE_DAYS`.
  - `POST /api/sync/push/` — envoi des changements locaux, merge champ à champ via la métadonnée
    `_changed`.
  - `POST /api/attachments/` / `DELETE /api/attachments/<uuid>/` — upload/suppression de pièces
    jointes.
  - `GET /api/administrative-levels/` — référentiel administratif paginé pour alimentation du
    cache local mobile.
  - `GET /api/sync/inactive-devices/` — appareils n'ayant pas synchronisé depuis
    `SYNC_INACTIVE_DEVICE_DAYS`.
- **API inter-plateformes** (`api/service/`) : ADL (liste, par email, par village), villages avec
  ADL, changement de mot de passe utilisateur, référentiels de catégories/statuts de plaintes,
  liste et statistiques de plaintes par assigné.
- **Documentation interactive** : Swagger disponible en mode `DEBUG` sur `/swagger/`.

Le détail complet du protocole de synchronisation, du mapping CouchDB → PostgreSQL et des
scripts de migration de données est dans [`CLAUDE.md`](./CLAUDE.md).

## Stack technique

- **Django 3.2** + **Django REST Framework**, `drf-yasg` (Swagger)
- **PostgreSQL** (base applicative `grm_db`) + **MySQL** (référentiel externe `mis`, lecture)
- **djangorestframework-simplejwt** (auth JWT mobile/service)
- **Celery** + **django-celery-beat** + **Redis** (tâches planifiées : nettoyage des tombstones,
  pièces jointes orphelines, notifications)
- **django-storages** (S3) pour le stockage des pièces jointes en production
- **Twilio** (SMS), **Mapbox** (cartographie des plaintes)
- **CouchDB** (`cloudant`) conservé pendant la période de transition pour les flux non encore
  migrés

## Installation

```bash
cd grm-backend/src
python -m venv venv        # ou utiliser l'environnement dédié : D:\COSO\PROJECTS\GRM\backend\venv_grm
venv\Scripts\activate
pip install -r requirements.txt
```

Créer la base PostgreSQL :

```sql
CREATE DATABASE grm_db;
-- identifiants par défaut en développement : user postgres / password root
```

Copier `grm/.env.example` vers `grm/.env` (ou `grm/dev.env`/`grm/local.env` selon
l'environnement) et renseigner les variables (voir section suivante), puis :

```bash
python manage.py migrate
python manage.py createsuperuser
```

## Configuration (variables d'environnement)

Principales variables attendues (voir `grm/.env.example`) :

| Variable | Description |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | Configuration Django standard |
| `DATABASE_URL` | Connexion PostgreSQL (`postgres://postgres:root@localhost:5432/grm_db`) |
| `LEGACY_DATABASE_URL` | Connexion MySQL en lecture vers `mis` (référentiel administratif) |
| `COUCHDB_URL`, `COUCHDB_USERNAME`, `COUCHDB_PASSWORD` | Accès CouchDB legacy (`grm`, `eadls`, `grm_attachments`) pendant la transition |
| `CELERY_BROKER_URL` | Redis pour Celery |
| `MAPBOX_ACCESS_TOKEN`, `DIAGNOSTIC_MAP_*` | Configuration de la cartographie du dashboard |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Envoi de SMS |
| `S3_BUCKET`, `S3_ACCESS`, `S3_SECRET` | Stockage des pièces jointes |
| `CDD_URL_BASE`, `MIS_URL_BASE`, `GRM_URL_BASE` | Origines autorisées (CORS/CSRF) entre les trois plateformes |
| `GRM_SECRET_KEY_GENRATE` | Clé partagée pour authentifier les appels entrants de `service_api/` |

## Lancer le projet

```bash
python manage.py runserver 0.0.0.0:8002
```

Worker et planificateur Celery (nettoyage des tombstones, pièces jointes orphelines, alertes
d'appareils inactifs) :

```bash
celery -A grm worker -l info
celery -A grm beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## Tests

```bash
pytest
```

Les tests de synchronisation (`sync/tests/`) couvrent la création offline → push, le merge de
conflit champ à champ, la pagination du pull et la re-synchronisation forcée. Le référentiel
administratif (`mis`) n'étant jamais migré par les tests (`allow_migrate=False`), les tests qui en
ont besoin créent leurs propres fixtures via `AdministrativeLevel.objects.using('mis').create(...)`
plutôt que de lire des données réelles.

## Permissions / groupes

    - SuperAdmin            :
    - CDD Specialist        : CDDSpecialist
    - Admin                 : Admin
    - Evaluator             : Evaluator
    - Accountant            : Accountant
    - Regional Coordinator  : RegionalCoordinator
    - National Coordinator  : NationalCoordinator
    - General Manager       : GeneralManager
    - Director              : Director
    - Advisor               : Advisor
    - Minister               : Minister
    - Assignee              : Assignee
    - Viewer                : Viewer
    - Viewer of all issues  : ViewerOfAllIssues
    - Safeguard             : Safeguard
    - Privacy               : Privacy
    - Infra                 : Infra
    - Validator             : Validator

Les utilisateurs n'ont accès qu'aux plaintes dont le village (`administrative_region.administrative_id`)
figure dans leur périmètre (`administrative_regions`, `administrative_regions_objects...villages`,
`additional_administrative_regions`, `additional_administrative_regions_objects...villages`), à
l'exception des utilisateurs dont `administrative_region` vaut `1`, qui ont accès à toutes les
plaintes.

## Migration CouchDB → PostgreSQL

Ce dépôt est en cours de migration depuis une architecture CouchDB/PouchDB vers
PostgreSQL/WatermelonDB. L'ensemble de la feuille de route (mapping des données, protocole de
sync, scripts de migration, checklist d'avancement) est maintenu dans [`CLAUDE.md`](./CLAUDE.md).
