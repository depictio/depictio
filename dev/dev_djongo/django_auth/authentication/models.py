from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class EmailAddress(models.Model):
    """
    A custom implementation of django-allauth's EmailAddress model.
    This is needed to work around migration issues with Djongo.
    """

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="custom_email_addresses")
    email = models.EmailField(max_length=254, unique=True)
    verified = models.BooleanField(default=False)
    primary = models.BooleanField(default=False)

    class Meta:
        verbose_name = "email address"
        verbose_name_plural = "email addresses"

    def __str__(self):
        return self.email


class SocialAccount(models.Model):
    """
    A custom implementation of django-allauth's SocialAccount model.
    This is needed to work around migration issues with Djongo.
    """

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="custom_social_accounts")
    provider = models.CharField(max_length=30)
    uid = models.CharField(max_length=191)
    last_login = models.DateTimeField(default=timezone.now)
    date_joined = models.DateTimeField(default=timezone.now)
    extra_data = models.JSONField(default=dict)

    class Meta:
        unique_together = (("provider", "uid"),)

    def __str__(self):
        return f"{self.user} - {self.provider}"


class SocialToken(models.Model):
    """
    A custom implementation of django-allauth's SocialToken model.
    This is needed to work around migration issues with Djongo.
    """

    id = models.AutoField(primary_key=True)
    account = models.ForeignKey(SocialAccount, on_delete=models.CASCADE)
    token = models.TextField()
    token_secret = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Token for {self.account}"
