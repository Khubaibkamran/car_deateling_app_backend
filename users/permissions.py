from rest_framework.permissions import BasePermission

from .models import User


class IsCustomer(BasePermission):
    message = 'This is only available to customer accounts.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == User.Role.CUSTOMER)


class IsTechnician(BasePermission):
    message = 'This is only available to technician accounts.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == User.Role.TECHNICIAN)
