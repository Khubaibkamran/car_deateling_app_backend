from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import TechnicianProfile, User


class UserCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ('email', 'full_name', 'role')


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'


class TechnicianInline(admin.StackedInline):
    model = TechnicianProfile
    can_delete = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreationForm
    ordering = ('-date_joined',)
    list_display = ('email', 'full_name', 'role', 'phone', 'is_active', 'date_joined')
    list_filter = ('role', 'is_active', 'is_staff')
    search_fields = ('email', 'full_name', 'phone')
    inlines = [TechnicianInline]
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Profile', {'fields': ('full_name', 'phone', 'city', 'bio', 'photo', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'full_name', 'role', 'password1', 'password2')}),
    )
    filter_horizontal = ('groups', 'user_permissions')
