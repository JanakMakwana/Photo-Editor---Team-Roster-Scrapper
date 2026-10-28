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

    def remaining_seats(self):
        return max(0, self.max_seats - self.used_seats())

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
    ROLE_CHOICES = (
        ('superadmin', 'SuperAdmin (Platform Root)'),
        ('company_admin', 'Company Admin (Team Manager)'),
        ('member', 'Company Member (Standard User)'),
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
        return self.role == 'superadmin' or self.is_superuser

    def __str__(self):
        return f"{self.email} ({self.role})"



class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='invitations')
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=50, default='member')
    token = models.CharField(max_length=128, unique=True)
    is_accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Invite for {self.email} to {self.company.name}"
