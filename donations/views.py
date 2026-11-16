import logging
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from communities.models import Community, Need

from . import services, webhooks
from .forms import OTHER, OneTimeDonationForm, SubscriptionForm
from .gateway import MercadoPagoError, MercadoPagoNotConfigured
from .models import DonorTier, OneTimeDonation, Subscription

logger = logging.getLogger('donations')

# Dominios a los que se permite redirigir al usuario para pagar.
ALLOWED_CHECKOUT_HOSTS = ('mercadopago.com', 'mercadolibre.com', 'mercadopago.com.ar', 'mercadolibre.com.ar')


def _safe_checkout_redirect(url):
    host = urlparse(url).hostname or ''
    if not url.startswith('https://') or not any(host == h or host.endswith('.' + h) for h in ALLOWED_CHECKOUT_HOSTS):
        raise MercadoPagoError(f'URL de checkout inesperada: {url}')
    return HttpResponseRedirect(url)


def _context_target(request):
    """Comunidad / necesidad elegida (opcional), validada contra la base."""
    community = need = None
    need_id = request.GET.get('necesidad') or request.POST.get('need')
    community_id = request.GET.get('comunidad') or request.POST.get('community')
    if need_id and str(need_id).isdigit():
        need = Need.objects.filter(pk=need_id, status=Need.Status.ACTIVE, community__is_active=True) \
            .select_related('community').first()
        community = need.community if need else None
    if community is None and community_id and str(community_id).isdigit():
        community = Community.objects.filter(pk=community_id, is_active=True).first()
    return community, need


def _owned_or_404(model, reference, user):
    obj = get_object_or_404(model, reference=reference)
    if obj.user_id != user.pk and not user.is_staff:
        raise PermissionDenied
    return obj


def _mp_error_message(exc):
    if isinstance(exc, MercadoPagoNotConfigured):
        return 'Las donaciones online todavía no están habilitadas. Probá más tarde.'
    return 'No pudimos conectar con Mercado Pago. Intentá nuevamente en unos minutos.'


# ---------------------------------------------------------------------------
# Inicio del flujo: elegir donación única o mensual
# ---------------------------------------------------------------------------
def donate_start(request):
    community, need = _context_target(request)
    return render(request, 'donations/start.html', {
        'community': community,
        'need': need,
        'tiers': DonorTier.objects.filter(is_active=True),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def one_time(request):
    community, need = _context_target(request)
    initial = {'community': community, 'need': need, 'amount_choice': None}
    form = OneTimeDonationForm(request.POST or None, initial=initial)

    if request.method == 'POST' and form.is_valid():
        try:
            donation = services.create_one_time_donation(
                request.user,
                form.cleaned_data['amount'],
                community=form.cleaned_data.get('community'),
                need=form.cleaned_data.get('need'),
            )
            return _safe_checkout_redirect(donation.checkout_url)
        except MercadoPagoError as exc:
            logger.warning('No se pudo crear la orden: %s', exc)
            messages.error(request, _mp_error_message(exc))

    return render(request, 'donations/one_time.html', {
        'form': form,
        'community': community,
        'need': need,
        'other_value': OTHER,
    })


@login_required
def donation_detail(request, reference):
    """Resultado/detalle de una donación. También es la URL de retorno de Checkout Pro.

    Los parámetros que agrega Mercado Pago a la URL se ignoran: el estado se
    consulta directamente a la API.
    """
    donation = _owned_or_404(OneTimeDonation, reference, request.user)
    if not donation.is_final and donation.mp_order_id:
        try:
            donation = services.refresh_donation(donation)
        except MercadoPagoError as exc:
            logger.info('No se pudo actualizar la donación %s: %s', donation.pk, exc)
    return render(request, 'donations/donation_detail.html', {'donation': donation})


# ---------------------------------------------------------------------------
# Donación mensual (suscripciones)
# ---------------------------------------------------------------------------
def monthly(request):
    return render(request, 'donations/monthly.html', {
        'tiers': DonorTier.objects.filter(is_active=True),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def subscribe(request, slug):
    tier = get_object_or_404(DonorTier, slug=slug, is_active=True)
    form = SubscriptionForm(request.POST or None, initial={'payer_email': request.user.email})

    if request.method == 'POST' and form.is_valid():
        try:
            subscription = services.create_subscription(request.user, tier, form.cleaned_data['payer_email'])
            return _safe_checkout_redirect(subscription.init_point)
        except MercadoPagoError as exc:
            logger.warning('No se pudo crear la suscripción: %s', exc)
            messages.error(request, _mp_error_message(exc))

    return render(request, 'donations/subscribe.html', {'tier': tier, 'form': form})


@login_required
def subscription_detail(request, reference):
    """Detalle de la suscripción. También es el back_url de Mercado Pago."""
    subscription = _owned_or_404(Subscription, reference, request.user)
    if subscription.mp_preapproval_id and subscription.status not in (
            Subscription.Status.CANCELLED, Subscription.Status.ERROR):
        try:
            subscription = services.refresh_subscription(subscription)
        except MercadoPagoError as exc:
            logger.info('No se pudo actualizar la suscripción %s: %s', subscription.pk, exc)
    return render(request, 'donations/subscription_detail.html', {
        'subscription': subscription,
        'payments': subscription.payments.all()[:24],
    })


@login_required
@require_http_methods(['GET', 'POST'])
def subscription_cancel(request, reference):
    subscription = _owned_or_404(Subscription, reference, request.user)
    if not subscription.can_be_cancelled:
        messages.info(request, 'Esta suscripción ya no está activa.')
        return redirect(subscription)

    if request.method == 'POST':
        try:
            services.cancel_subscription(subscription)
            messages.success(request, 'Tu suscripción fue cancelada. ¡Gracias por haber acompañado!')
        except MercadoPagoError as exc:
            logger.warning('No se pudo cancelar la suscripción %s: %s', subscription.pk, exc)
            messages.error(request, 'No pudimos cancelar la suscripción en Mercado Pago. Intentá nuevamente.')
        return redirect(subscription)

    return render(request, 'donations/subscription_cancel.html', {'subscription': subscription})


# ---------------------------------------------------------------------------
# Panel del donador
# ---------------------------------------------------------------------------
@login_required
def my_activity(request):
    return render(request, 'donations/my_activity.html', {
        'donations': request.user.online_donations.select_related('community', 'need')
                                                  .exclude(status=OneTimeDonation.Status.ERROR),
        'subscriptions': request.user.donation_subscriptions.select_related('tier')
                                                            .exclude(status=Subscription.Status.ERROR),
    })


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
@csrf_exempt  # Mercado Pago no envía token CSRF; la autenticidad se valida con x-signature.
@require_POST
def mercadopago_webhook(request):
    return HttpResponse(status=webhooks.handle(request))
