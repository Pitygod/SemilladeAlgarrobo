from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from donations import services
from donations.gateway import MercadoPagoError
from donations.models import OneTimeDonation, Subscription


class Command(BaseCommand):
    help = ('Verifica en Mercado Pago el estado de donaciones y suscripciones no finalizadas. '
            'Respaldo por si alguna notificación (webhook) no llegó. Se puede programar con cron.')

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=30, help='Antigüedad máxima a revisar (default 30).')

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(days=options['dias'])
        donations = list(OneTimeDonation.objects.filter(created_at__gte=since).exclude(mp_order_id=None)
                         .exclude(status__in=OneTimeDonation.FINAL_STATUSES))
        subscriptions = list(Subscription.objects.exclude(mp_preapproval_id=None)
                             .exclude(status__in=[Subscription.Status.CANCELLED, Subscription.Status.ERROR]))
        errors = 0
        for donation in donations:
            try:
                services.refresh_donation(donation)
            except MercadoPagoError as exc:
                errors += 1
                self.stderr.write(f'Donación {donation.pk}: {exc}')
        for subscription in subscriptions:
            try:
                services.refresh_subscription(subscription)
            except MercadoPagoError as exc:
                errors += 1
                self.stderr.write(f'Suscripción {subscription.pk}: {exc}')
        self.stdout.write(self.style.SUCCESS(
            f'Revisadas {len(donations)} donaciones y {len(subscriptions)} suscripciones ({errors} errores).'
        ))
