from django.contrib.auth.models import User
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from .models import SocialAccount, EmailAddress


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter for social accounts that uses our custom models
    instead of django-allauth's models.
    """

    def save_user(self, request, sociallogin, form=None):
        """
        Save the user and create our custom SocialAccount and EmailAddress models
        """
        user = super().save_user(request, sociallogin, form)

        # Create our custom SocialAccount
        social_data = sociallogin.account.get_provider_account().get_avatar_url()
        extra_data = sociallogin.account.extra_data

        # First, clean up any duplicate entries in django-allauth's SocialAccount model
        self.clean_allauth_accounts(sociallogin.account.provider, sociallogin.account.uid)

        # Then, handle our custom SocialAccount model
        # Check if there are any existing SocialAccount entries for this user and provider
        existing_accounts = SocialAccount.objects.filter(
            user=user, provider=sociallogin.account.provider, uid=sociallogin.account.uid
        )

        # If there are multiple accounts, keep only one and delete the rest
        if existing_accounts.count() > 1:
            # Keep the first one and delete the rest
            account_to_keep = existing_accounts.first()
            for account in existing_accounts[1:]:
                account.delete()

            # Update the account we're keeping
            account_to_keep.extra_data = extra_data
            account_to_keep.save()
            social_account = account_to_keep
        else:
            # Create or update our custom SocialAccount
            social_account, created = SocialAccount.objects.update_or_create(
                user=user,
                provider=sociallogin.account.provider,
                uid=sociallogin.account.uid,
                defaults={"extra_data": extra_data},
            )

        # Create or update our custom EmailAddress for each email
        for email in sociallogin.email_addresses:
            email_address, created = EmailAddress.objects.update_or_create(
                user=user,
                email=email.email,
                defaults={"verified": email.verified, "primary": email.primary},
            )

        return user

    def clean_allauth_accounts(self, provider, uid):
        """
        Clean up duplicate entries in django-allauth's SocialAccount model
        """
        try:
            # Import django-allauth's SocialAccount model
            from allauth.socialaccount.models import SocialAccount as AllauthSocialAccount

            # Get all social accounts with the same provider and uid
            allauth_accounts = AllauthSocialAccount.objects.filter(provider=provider, uid=uid)

            # If there are multiple accounts, keep only one and delete the rest
            if allauth_accounts.count() > 1:
                # Keep the first one and delete the rest
                account_to_keep = allauth_accounts.first()
                for account in allauth_accounts[1:]:
                    # Check if the account has a valid ID before deleting
                    if account.id is not None:
                        account.delete()
        except ImportError:
            # django-allauth's SocialAccount model not found
            pass
        except Exception as e:
            # Log the error but don't fail the login process
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error cleaning allauth accounts: {str(e)}")

    def get_callback_url(self, request, sociallogin):
        """
        Override the default callback URL to use our custom endpoint
        """
        # Use the absolute URL for the callback to ensure it's correct
        return request.build_absolute_uri("/accounts/google/login/callback/")


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Custom adapter for accounts that uses our custom models
    instead of django-allauth's models.
    """

    def populate_username(self, request, user):
        """
        Fills in a valid username, if required and missing.
        """
        from django.contrib.auth.models import User

        username = user.username
        if not username:
            # Generate a unique username based on email
            email = user.email
            username = email.split("@")[0]

            # Make sure it's unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user.username = username

        return user
