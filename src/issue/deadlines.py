"""Délais de traitement des plaintes par niveau (comité), cf. `issue.models.ProcessingDelay`.

Règles :
- Niveau d'une plainte = niveau le plus haut atteint par escalade (`EscalationLevel`), sinon
  Village. On ne se fie pas à l'ordre des dates : dans les données migrées de CouchDB, les
  niveaux d'une même plainte ont la même date.
- Départ du délai : Village → date exacte de réception (`Issue.received_date`, à défaut
  `intake_date`) ; niveau escaladé → date réelle de l'escalade vers ce niveau
  (`EscalationLevel.escalation_date`, à défaut `due_at`).
- Échéance = départ + N jours (ouvrables : lundi → vendredi, jours fériés non pris en compte ;
  ou calendaires selon le paramétrage). Le jour de départ n'est pas compté.
- Plainte « en retard » : ni résolue ni rejetée, et aujourd'hui > échéance.
- « Résolue dans les délais » : date de résolution (réelle sur le terrain, sinon date
  d'enregistrement de la résolution, sinon première ligne d'historique « Résolue ») ≤ échéance.

Le mobile applique les mêmes règles (grm-frontend/src/utils/issueDeadlines.js).
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Min
from django.utils import timezone

from issue.models import EscalationLevel, IssueStatusStory, ProcessingDelay

LEVEL_ORDER = ProcessingDelay.LEVEL_ORDER
LEVEL_RANK = {level: index for index, level in enumerate(LEVEL_ORDER)}


def to_local_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def add_delay(start, days, working_days=True):
    """Date d'échéance : `start` + `days` jours (ouvrables ou calendaires), jour de départ exclu."""
    if not working_days:
        return start + timedelta(days=days)
    current, remaining = start, days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # lundi (0) → vendredi (4)
            remaining -= 1
    return current


def normalize_level(value):
    """'canton' / 'CANTON' → 'Canton' ; niveau inconnu → None."""
    value = (value or '').strip().capitalize()
    return value if value in LEVEL_RANK else None


def load_delays():
    """{niveau: ProcessingDelay} pour les niveaux dont le délai est renseigné."""
    return {
        delay.level: delay
        for delay in ProcessingDelay.objects.filter(is_deleted=False, delay_days__isnull=False)
    }


@dataclass
class DeadlineInfo:
    level: str
    start: date
    delay: ProcessingDelay = None
    deadline: date = None
    closed: bool = False
    resolved: bool = False
    resolution_date: date = None
    overdue: bool = False
    days_late: int = 0
    resolved_in_time: bool = None  # None : non résolue, délai non défini ou date de résolution inconnue


def compute_deadline_infos(issues, today=None, delays=None):
    """{issue.pk: DeadlineInfo} pour une liste d'`Issue` (avec `status` chargé)."""
    today = today or timezone.localdate()
    delays = load_delays() if delays is None else delays
    issue_ids = [issue.pk for issue in issues]

    # Niveau le plus haut atteint + date d'arrivée (la plus ancienne) à ce niveau.
    escalations = {}
    rows = EscalationLevel.objects.filter(issue_id__in=issue_ids, is_deleted=False).values_list(
        'issue_id', 'administrative_level', 'escalation_date', 'due_at',
    )
    for issue_id, raw_level, escalation_date, due_at in rows:
        level = normalize_level(raw_level)
        if not level:
            continue
        arrival = to_local_date(escalation_date or due_at)
        current = escalations.get(issue_id)
        if current is None or LEVEL_RANK[level] > LEVEL_RANK[current[0]]:
            escalations[issue_id] = (level, arrival)
        elif level == current[0] and arrival and (current[1] is None or arrival < current[1]):
            escalations[issue_id] = (level, arrival)

    # Date de résolution de repli : première ligne d'historique au statut final.
    missing = [
        issue.pk for issue in issues
        if issue.status and issue.status.final_status
        and not (issue.resolution_real_issue_date or issue.resolution_date)
    ]
    story_dates = dict(
        IssueStatusStory.objects.filter(issue_id__in=missing, is_deleted=False, status__final_status=True)
        .values('issue_id').annotate(first=Min('datetime')).values_list('issue_id', 'first')
    ) if missing else {}

    infos = {}
    for issue in issues:
        if issue.pk in escalations:
            level, start = escalations[issue.pk]
        else:
            level, start = ProcessingDelay.LEVEL_VILLAGE, None
        if start is None:
            start = to_local_date(issue.received_date or issue.intake_date)

        status = issue.status
        resolved = bool(status and status.final_status)
        closed = resolved or bool(status and status.rejected_status)
        info = DeadlineInfo(level=level, start=start, closed=closed, resolved=resolved)

        delay = delays.get(level)
        if delay and start:
            info.delay = delay
            info.deadline = add_delay(start, delay.delay_days, delay.working_days)

        if resolved:
            info.resolution_date = to_local_date(
                issue.resolution_real_issue_date or issue.resolution_date or story_dates.get(issue.pk)
            )
            if info.deadline and info.resolution_date:
                info.resolved_in_time = info.resolution_date <= info.deadline
        elif not closed and info.deadline and today > info.deadline:
            info.overdue = True
            info.days_late = (today - info.deadline).days

        infos[issue.pk] = info
    return infos


def overdue_by_village(issues, infos):
    """[{village_id, village_name, count}] des plaintes en retard, le plus de retards d'abord."""
    villages = {}
    for issue in issues:
        info = infos.get(issue.pk)
        if not info or not info.overdue:
            continue
        key = issue.administrative_region_id
        entry = villages.setdefault(key, {
            'village_id': key, 'village_name': issue.administrative_region_name or str(key or '-'), 'count': 0,
        })
        entry['count'] += 1
    return sorted(villages.values(), key=lambda v: (-v['count'], v['village_name']))


def overdue_issues(queryset, today=None):
    """Plaintes en retard d'un QuerySet d'`Issue` (périmètre d'un utilisateur) :
    [(issue, DeadlineInfo)], la plus en retard d'abord. Les plaintes résolues/rejetées sont
    écartées dès la requête."""
    from django.db.models import Q

    issues = list(
        queryset.select_related('status').exclude(Q(status__final_status=True) | Q(status__rejected_status=True))
    )
    infos = compute_deadline_infos(issues, today=today)
    late = [(issue, infos[issue.pk]) for issue in issues if infos[issue.pk].overdue]
    return sorted(late, key=lambda pair: -pair[1].days_late), infos
