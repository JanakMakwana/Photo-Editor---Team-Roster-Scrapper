from django.core.management.base import BaseCommand
from apps.accounts.models import Company, User


class Command(BaseCommand):
    help = 'Seeds initial company and superadmin user for VeloRoster Pro'

    def handle(self, *args, **options):
        company, c_created = Company.objects.get_or_create(
            slug='athletics-media',
            defaults={
                'name': 'Athletics Media Group',
                'plan': 'enterprise',
                'max_seats': 25,
                'status': 'active'
            }
        )
        if c_created:
            self.stdout.write(self.style.SUCCESS(f'Created default company: {company.name}'))
        else:
            self.stdout.write(f'Company already exists: {company.name}')

        # Create or update SuperAdmin
        admin_email = 'admin@athletics.com'
        admin_user = User.objects.filter(email=admin_email).first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                email=admin_email,
                password='admin',
                full_name='System SuperAdmin',
                company=company,
                role='superadmin'
            )
            self.stdout.write(self.style.SUCCESS(f'Created SuperAdmin: {admin_email} / admin'))
        else:
            admin_user.set_password('admin')
            admin_user.role = 'superadmin'
            admin_user.is_superuser = True
            admin_user.is_staff = True
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f'Updated SuperAdmin credentials for: {admin_email}'))

        # Create or update Demo Team Member
        member_email = 'coach@athletics.com'
        member_user = User.objects.filter(email=member_email).first()
        if not member_user:
            member_user = User.objects.create_user(
                email=member_email,
                password='admin',
                full_name='Head Coach Alex',
                company=company,
                role='company_admin'
            )
            self.stdout.write(self.style.SUCCESS(f'Created Team Admin: {member_email} / admin'))
