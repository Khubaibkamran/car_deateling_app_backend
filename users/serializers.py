from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import TechnicianProfile, User


class TechnicianProfileSerializer(serializers.ModelSerializer):
    employee_code = serializers.CharField(read_only=True)

    class Meta:
        model = TechnicianProfile
        fields = ['employee_code', 'specialty', 'experience', 'is_available', 'rating', 'rating_count', 'jobs_completed']
        read_only_fields = ['employee_code', 'rating', 'rating_count', 'jobs_completed']


class UserSerializer(serializers.ModelSerializer):
    technician = TechnicianProfileSerializer(source='technician_profile', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'phone', 'city', 'bio', 'photo', 'role', 'technician', 'date_joined']
        read_only_fields = fields


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Fields the Edit Profile screen can change. Technician-only fields are ignored for customers."""

    specialty = serializers.CharField(required=False, allow_blank=True, max_length=100)
    experience = serializers.CharField(required=False, allow_blank=True, max_length=50)
    is_available = serializers.BooleanField(required=False)
    remove_photo = serializers.BooleanField(required=False, write_only=True, default=False)

    class Meta:
        model = User
        fields = ['full_name', 'phone', 'city', 'bio', 'photo', 'specialty', 'experience', 'is_available', 'remove_photo']
        extra_kwargs = {'full_name': {'required': False}, 'photo': {'required': False}}

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Name cannot be empty.')
        return value

    def update(self, instance, validated):
        remove_photo = validated.pop('remove_photo', False)
        tech_fields = {k: validated.pop(k) for k in ('specialty', 'experience', 'is_available') if k in validated}
        if remove_photo and instance.photo:
            instance.photo.delete(save=False)
            instance.photo = None
        instance = super().update(instance, validated)
        if tech_fields and instance.is_technician:
            profile = instance.technician_profile
            for key, value in tech_fields.items():
                setattr(profile, key, value)
            profile.save()
        return instance


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    role = serializers.ChoiceField(choices=User.Role.choices, default=User.Role.CUSTOMER)

    class Meta:
        model = User
        fields = ['email', 'password', 'full_name', 'phone', 'role']

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Please enter your name.')
        return value

    def validate(self, attrs):
        # Validate the password against the user's details (e.g. not too similar to the email).
        candidate = User(email=attrs['email'], full_name=attrs.get('full_name', ''))
        try:
            password_validation.validate_password(attrs['password'], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated):
        password = validated.pop('password')
        user = User.objects.create_user(password=password, **validated)
        if user.role == User.Role.TECHNICIAN:
            TechnicianProfile.objects.create(user=user)
        return user


class LoginSerializer(TokenObtainPairSerializer):
    """Email + password. Pass `role` to make sure a customer can't sign in to the technician app and vice versa."""

    role = serializers.ChoiceField(choices=User.Role.choices, required=False, write_only=True)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        return token

    def validate(self, attrs):
        attrs[self.username_field] = attrs.get(self.username_field, '').strip().lower()
        wanted_role = attrs.pop('role', None)
        data = super().validate(attrs)
        if wanted_role and self.user.role != wanted_role:
            raise serializers.ValidationError(
                {'role': f'This is a {self.user.get_role_display().lower()} account. Please use the {self.user.role} sign-in.'}
            )
        data['user'] = UserSerializer(self.user, context=self.context).data
        return data


class GoogleLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(write_only=True)
    # Left out on the shared sign-in screen: an existing account keeps its role, a new one is a customer.
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Your current password is incorrect.')
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, self.context['request'].user)
        return value


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


# ---- password reset ----

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)


class VerifyCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r'^\d{6}$', error_messages={'invalid': 'Enter the 6-digit code.'})


class ResetPasswordSerializer(serializers.Serializer):
    reset_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
