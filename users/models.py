from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError('An email address is required.')
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        extra.setdefault('role', User.Role.CUSTOMER)
        return self._create(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Customers and technicians share one account table; `role` says which app they use."""

    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        TECHNICIAN = 'technician', 'Technician'

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    city = models.CharField(max_length=100, blank=True)
    bio = models.CharField(max_length=200, blank=True)
    photo = models.ImageField(upload_to='profiles/%Y/%m/', blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        ordering = ['-date_joined']

    def __str__(self) -> str:
        return f'{self.full_name} <{self.email}>'

    @property
    def is_technician(self) -> bool:
        return self.role == self.Role.TECHNICIAN

    @property
    def first_name(self) -> str:
        return self.full_name.split(' ')[0] if self.full_name else ''


class TechnicianProfile(models.Model):
    """Extra details only technicians have."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='technician_profile')
    specialty = models.CharField(max_length=100, blank=True)
    experience = models.CharField(max_length=50, blank=True)
    is_available = models.BooleanField(default=True)
    # Cached from reviews so lists don't have to aggregate every time.
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    jobs_completed = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f'Technician {self.user.full_name}'

    @property
    def employee_code(self) -> str:
        return f'{self.user_id:07d}'


class PasswordResetCode(models.Model):
    """A short-lived 6-digit code emailed to someone who forgot their password."""

    MAX_ATTEMPTS = 5
    LIFETIME = timedelta(minutes=10)

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_codes')
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def issue(cls, user: User, code: str) -> 'PasswordResetCode':
        # Any earlier unused codes stop working.
        cls.objects.filter(user=user, used=False).update(used=True)
        return cls.objects.create(user=user, code_hash=make_password(code), expires_at=timezone.now() + cls.LIFETIME)

    @property
    def is_usable(self) -> bool:
        return not self.used and self.attempts < self.MAX_ATTEMPTS and self.expires_at > timezone.now()

    def verify(self, code: str) -> bool:
        self.attempts += 1
        self.save(update_fields=['attempts'])
        return self.is_usable and check_password(code, self.code_hash)
