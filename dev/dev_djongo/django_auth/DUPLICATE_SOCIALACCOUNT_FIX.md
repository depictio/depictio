# Fix for MultipleObjectsReturned Error in Google OAuth Login

This document explains the fix for the error: `MultipleObjectsReturned: get() returned more than one SocialAccount -- it returned 2!`

## The Issue

The error occurs during Google OAuth login when multiple SocialAccount objects exist for the same user, provider, and UID. This can happen due to:

1. Race conditions during login
2. Interrupted login processes
3. Migration issues between django-allauth and custom models

## The Fix

We've implemented several fixes to address this issue:

### 1. Modified the CustomSocialAccountAdapter

The `CustomSocialAccountAdapter.save_user()` method now:
- Checks for existing SocialAccount entries in our custom model before creating a new one
- If multiple entries are found, it keeps only the first one and deletes the rest
- Cleans up duplicate entries in django-allauth's SocialAccount model as well

### 2. Added Safeguard in GoogleCallbackView

The `GoogleCallbackView.get()` method now includes a safeguard that checks for multiple SocialAccount entries for the current user and Google provider. If multiple entries are found, it keeps only the first one and deletes the rest.

### 3. Updated URL Configuration

The URL configuration has been updated to use the GoogleCallbackView directly for the `/accounts/google/login/callback/` path, eliminating the redirect that might have contributed to the issue.

### 4. Added a Management Command to Clean Up Existing Duplicates

A management command has been added to clean up any existing duplicate SocialAccount entries in both our custom model and django-allauth's model.

## How to Run the Cleanup Command

To clean up existing duplicate SocialAccount entries, run:

```bash
cd django_auth
python manage.py clean_social_accounts
```

This command will:
1. Find all users with multiple SocialAccount entries for the same provider and UID
2. Keep the first entry and delete the rest
3. Report how many duplicate entries were cleaned up

> **Note**: The command has been optimized to work with Djongo (MongoDB connector for Django) by avoiding complex SQL queries that might not be fully supported by the Djongo SQL-to-MongoDB translator.

## Testing the Fix

After applying these fixes, you should be able to log in with Google OAuth without encountering the MultipleObjectsReturned error. The login process should complete successfully and redirect you to the Dash frontend with the appropriate tokens.

## Monitoring

If you continue to experience issues, check the Django logs for any errors. You can also run the cleanup command periodically to ensure no new duplicate entries are created.
