from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = 'Cambia la contraseña de un usuario existente en la base de datos'

    def add_arguments(self, parser):
        parser.add_argument('email')

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options['email'])
        except User.DoesNotExist:
            raise CommandError(f"No existe el usuario {options['email']}")
        password = getpass('Nueva contraseña: ')
        if not password:
            raise CommandError('La contraseña no puede estar vacía.')
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f'Contraseña actualizada: {user.username}'))
