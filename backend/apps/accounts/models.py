import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone


class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    default_max_seats = models.IntegerField(default=10)
    price_monthly = models.CharField(max_length=50, default='$0')
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['default_max_seats']

    def __str__(self):
        return f"{self.name} ({self.default_max_seats} seats - {self.price_monthly}/mo)"


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    plan = models.CharField(max_length=50, default='team')  # free, team, enterprise
    max_seats = models.IntegerField(default=10)
    status = models.CharField(max_length=50, default='active')  # active, suspended
    created_at = models.DateTimeField(default=timezone.now)

    def used_seats(self):
        return self.members.filter(is_active=True).exclude(role='superadmin').count()

    def pending_invitations_count(self):
        now = timezone.now()
        return self.invitations.filter(is_accepted=False, is_revoked=False).exclude(
            expires_at__isnull=False, expires_at__lt=now
        ).count()

    def remaining_seats(self):
        return max(0, self.max_seats - self.used_seats() - self.pending_invitations_count())

    def __str__(self):
        return f"{self.name} ({self.plan})"


class UserManager(BaseUserManager):
    def get_by_natural_key(self, username):
        return self.get(models.Q(email__iexact=username) | models.Q(username__iexact=username))

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email address is required')
        email = self.normalize_email(email).lower()
        extra_fields.setdefault('username', email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'superadmin')
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    ROLE_SUPERADMIN = 'superadmin'
    ROLE_COMPANY_ADMIN = 'company_admin'
    ROLE_MEMBER = 'member'
    ROLE_VIEWER = 'viewer'

    ROLE_CHOICES = (
        (ROLE_SUPERADMIN, 'SuperAdmin (Platform Root)'),
        (ROLE_COMPANY_ADMIN, 'Company Admin (Team Manager)'),
        (ROLE_MEMBER, 'Company Member (Standard User)'),
        (ROLE_VIEWER, 'Company Viewer (Read Only)'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='member')
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=128, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
            if not self.username or self.username != self.email:
                self.username = self.email
        super().save(*args, **kwargs)

    def is_superadmin_user(self):
        return self.role == self.ROLE_SUPERADMIN or self.is_superuser

    def is_company_admin_user(self):
        return self.is_superadmin_user() or self.role == self.ROLE_COMPANY_ADMIN

    def can_manage_company(self, target_company):
        if not target_company:
            return False
        if self.is_superadmin_user():
            return True
        return self.role == self.ROLE_COMPANY_ADMIN and self.company_id == target_company.id

    def __str__(self):
        return f"{self.email} ({self.role})"



class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='invitations')
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_invitations')
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=50, default='member')
    token = models.CharField(max_length=128, unique=True)
    is_accepted = models.BooleanField(default=False)
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def is_expired(self):
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    def is_valid(self):
        return (not self.is_accepted) and (not self.is_revoked) and (not self.is_expired())

    def __str__(self):
        return f"Invite for {self.email} to {self.company.name} ({self.role})"

