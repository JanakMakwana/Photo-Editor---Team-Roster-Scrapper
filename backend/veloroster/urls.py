from django.contrib import admin
from django.urls import path
from apps.accounts import views as auth_views
from apps.studio import views as studio_views
from apps.roster import views as roster_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Health Checks
    path('healthz', studio_views.api_health),
    path('health', studio_views.api_health),
    path('api/health', studio_views.api_health),

    # Authentication & Multi-Tenant Seats
    path('api/auth/me', auth_views.api_me),
    path('api/auth/login', auth_views.api_login),
    path('api/auth/logout', auth_views.api_logout),
    path('api/auth/activate', auth_views.api_activate_invite),
    path('api/admin/dashboard_stats', auth_views.api_dashboard_stats),
    path('api/company/users/invite', auth_views.api_invite_user),

    # Studio & Portrait Tools
    path('api/auto_align', studio_views.api_auto_align),
    path('api/cutout', studio_views.api_cutout),
    path('api/suggested_folders', studio_views.api_suggested_folders),
    path('api/open_folder', studio_views.api_open_folder),
    path('api/save_photo', studio_views.api_save_photo),
    path('api/batch_process', studio_views.api_batch_process),
    path('api/download_edited_zip', studio_views.api_download_edited_zip),
    path('api/clear_server_storage', studio_views.api_clear_server_storage),

    # Roster & Search
    path('api/fetch_roster', roster_views.api_fetch_roster),
    path('api/proxy_photo', roster_views.api_proxy_photo),
    path('api/download_roster_zip', roster_views.api_download_roster_zip),
]
