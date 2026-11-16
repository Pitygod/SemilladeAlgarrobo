"""Cálculo de la comunidad con mayor necesidad actual.

Usa solo datos que el proyecto ya registra en cada necesidad (``Need``):
estado activa, urgencia, categoría y cuánto falta recaudar. Los pesos se
configuran en ``settings.NEED_PRIORITY_WEIGHTS``.

Puntaje de una necesidad activa =
    active_need
  + urgent (si está marcada como urgente)
  + peso de su categoría
  + remaining_ratio × (fracción que falta cubrir, de 0 a 1)

Puntaje de la comunidad = suma de sus necesidades activas.
"""
from decimal import Decimal

from django.conf import settings
from django.db.models import Prefetch, Sum

from .models import Community, Need


def need_score(need, raised=None):
    if need.status != Need.Status.ACTIVE:
        return 0.0
    weights = settings.NEED_PRIORITY_WEIGHTS
    score = weights.get('active_need', 1.0)
    if need.is_urgent:
        score += weights.get('urgent', 0.0)
    score += weights.get('categories', {}).get(need.category, 0.0)
    if need.target_amount and need.target_amount > 0:
        raised = need.raised_amount if raised is None else (raised or Decimal('0'))
        remaining = max(need.target_amount - raised, Decimal('0'))
        score += weights.get('remaining_ratio', 0.0) * float(remaining / need.target_amount)
    return round(score, 2)


def ranked_communities(queryset=None):
    """Devuelve las comunidades activas ordenadas: destacadas a mano, luego por puntaje."""
    queryset = queryset if queryset is not None else Community.objects.filter(is_active=True)
    active_needs = Need.objects.filter(status=Need.Status.ACTIVE).annotate(raised=Sum('donations__amount'))
    communities = list(queryset.prefetch_related(
        'images',
        Prefetch('needs', queryset=active_needs, to_attr='active_needs'),
    ))
    for community in communities:
        community.priority_score = round(sum(need_score(n, n.raised) for n in community.active_needs), 2)
        community.urgent_active = sum(1 for n in community.active_needs if n.is_urgent)
        # Necesidades ordenadas por su propio puntaje para mostrar las principales.
        community.top_needs = sorted(community.active_needs, key=lambda n: -need_score(n, n.raised))
        # Una necesidad representativa por categoría (la de mayor prioridad), para los chips.
        by_category = {}
        for need in community.top_needs:
            by_category.setdefault(need.category, need)
        community.top_categories = list(by_category.values())
    communities.sort(key=lambda c: (not c.is_featured, -c.priority_score, c.name))
    return communities


def featured_and_others(queryset=None):
    communities = ranked_communities(queryset)
    if not communities:
        return None, []
    return communities[0], communities[1:]
