from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Company, Invitation, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'default_max_seats', 'price_monthly', 'is_active', 'created_at')
    list_editable = ('default_max_seats', 'price_monthly', 'is_active')
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'plan', 'max_seats', 'status', 'created_at')
    search_fields = ('name', 'slug')
    list_filter = ('plan', 'status')


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'full_name', 'company', 'role', 'is_staff', 'is_active')
    search_fields = ('email', 'full_name')
    list_filter = ('role', 'is_staff', 'is_active', 'company')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('full_name',)}),
        ('Organization & Role', {'fields': ('company', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'company', 'role', 'password', 'is_staff', 'is_active'),
        }),
    )


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'company', 'role', 'is_accepted', 'is_revoked', 'expires_at', 'invited_by', 'created_at')
    search_fields = ('email', 'full_name')
    list_filter = ('is_accepted', 'is_revoked', 'role', 'company')
    ordering = ('-created_at',)
