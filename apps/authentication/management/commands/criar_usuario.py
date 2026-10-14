"""Cria um usuário de API (para obter o token JWT)."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Cria (ou atualiza a senha de) um usuário para autenticar na API.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--password', required=True)
        parser.add_argument('--email', default='')
        parser.add_argument(
            '--superuser',
            action='store_true',
            help='Cria como superusuário (acesso ao admin Django).',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        usuario, _ = User.objects.get_or_create(
            username=options['username'],
            defaults={'email': options['email']},
        )
        usuario.set_password(options['password'])
        if options['superuser']:
            usuario.is_superuser = True
            usuario.is_staff = True
        usuario.save()
        self.stdout.write(
            self.style.SUCCESS(f"Usuário '{usuario.username}' pronto para usar a API.")
        )