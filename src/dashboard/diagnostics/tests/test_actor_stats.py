"""Statistiques « Plaintes par acteur » de /diagnostics/ (femmes, hommes, jeunes < 35 ans)."""
from types import SimpleNamespace

from dashboard.diagnostics.views import compute_actor_stats, is_youth_age_group


def _issue(gender=None, age=None, refugee=None):
    return SimpleNamespace(
        gender=gender, age_group=SimpleNamespace(name=age) if age else None, refugee_or_idp=refugee,
    )


def test_youth_age_groups():
    assert is_youth_age_group(SimpleNamespace(name='0 – 16'))
    assert is_youth_age_group(SimpleNamespace(name='17 – 35'))
    assert not is_youth_age_group(SimpleNamespace(name='36 – 50'))
    assert not is_youth_age_group(SimpleNamespace(name='65+'))
    assert not is_youth_age_group(None)


def test_actor_stats_counts_web_and_mobile_values():
    issues = [
        _issue('Female', '17 – 35'),  # web, jeune femme : compte dans 2 lignes
        _issue('female', '36 – 50'),  # mobile
        _issue('Male', '0 – 16'),
        _issue('male'),
        _issue(None, '17 – 35'),      # sexe non renseigné
        _issue('Rather not say', refugee=True),
        _issue('female', refugee=False),
    ]
    stats, gender_unknown = compute_actor_stats(issues)

    assert stats['women']['count'] == 3
    assert stats['men']['count'] == 2
    assert stats['youth']['count'] == 3
    assert gender_unknown == 2
    assert stats['refugees']['count'] == 1
    assert stats['women']['percentage'] == 43  # 3/7


def test_actor_stats_empty():
    stats, gender_unknown = compute_actor_stats([])
    assert all(line['count'] == 0 and line['percentage'] == 0 for line in stats.values())
    assert gender_unknown == 0
