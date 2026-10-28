import os
from django.core.management.base import BaseCommand
from apps.accounts.models import Company, User, Plan


class Command(BaseCommand):
    help = 'Seeds initial subscription plans, company, and superadmin for VeloRoster Pro'

    def handle(self, *args, **options):
        # 1. Seed Subscription Plans
        plans_data = [
            {'name': 'Free Tier', 'slug': 'free', 'default_max_seats': 3, 'price_monthly': '$0/mo', 'description': 'Standard athletic photo studio for single teams'},
            {'name': 'Team Tier', 'slug': 'team', 'default_max_seats': 15, 'price_monthly': '$49/mo', 'description': 'Collaborative roster tuner with AI cutout and batch exports'},
            {'name': 'Enterprise Tier', 'slug': 'enterprise', 'default_max_seats': 100, 'price_monthly': '$199/mo', 'description': 'Full league archive ingestion, 0 cloud storage, dedicated seats'},
        ]
        for p in plans_data:
            plan, p_created = Plan.objects.get_or_create(slug=p['slug'], defaults=p)
            if p_created:
                self.stdout.write(self.style.SUCCESS(f"Created Plan: {plan.name}"))

        # 2. Seed Default Organization
        org_name = os.environ.get('DEFAULT_ORG_NAME', 'Ecstaticloud Technologies')
        org_slug = os.environ.get('DEFAULT_ORG_SLUG', 'ecstaticloud-technologies')
        company, c_created = Company.objects.get_or_create(
            slug=org_slug,
            defaults={
                'name': org_name,
                'plan': 'enterprise',
                'max_seats': 50,
                'status': 'active'
            }
        )
        if c_created:
            self.stdout.write(self.style.SUCCESS(f'Created default company: {company.name}'))

        # 3. Seed SuperAdmin User
        admin_email = os.environ.get('SUPERADMIN_EMAIL', 'enterprise@ecstaticloud.com').strip().lower()
        admin_password = os.environ.get('SUPERADMIN_PASSWORD', 'admin').strip()

        admin_user = User.objects.filter(email=admin_email).first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                email=admin_email,
                password=admin_password,
                full_name='System SuperAdmin',
                company=company,
                role='superadmin'
            )
            self.stdout.write(self.style.SUCCESS(f'Created SuperAdmin: {admin_email}'))
        else:
            admin_user.role = 'superadmin'
            admin_user.is_superuser = True
            admin_user.is_staff = True
            if admin_password:
                admin_user.set_password(admin_password)
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f'Verified SuperAdmin: {admin_email}'))

