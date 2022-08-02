from functools import reduce
import operator
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.crypto import get_random_string
from rest_framework.authtoken.models import Token
from accounts.models import User
from zentral.conf import ConfigDict, settings


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class AccountUsersViewsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # ui user
        cls.ui_user = User.objects.create_user(
            get_random_string(),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
            is_superuser=False,
        )

        # group
        cls.ui_group = Group.objects.create(name=get_random_string())
        cls.ui_user.groups.set([cls.ui_group])
        # superuser
        cls.superuser = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
            is_superuser=True,
        )

        # user
        cls.pwd = get_random_string(18)
        cls.user = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
        )

        # remote user
        cls.remoteuser = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(45),
            is_remote=True,
        )

    # auth utils

    def login_redirect(self, url_name, *args):
        url = reverse(f"accounts:{url_name}", args=args)
        response = self.client.get(url)
        self.assertRedirects(response, "{u}?next={n}".format(u=reverse("login"), n=url))

    def permission_denied(self, url_name, *args):
        url = reverse(f"accounts:{url_name}", args=args)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def login(self, *permissions):
        if permissions:
            permission_filter = reduce(operator.or_, (
                Q(content_type__app_label=app_label, codename=codename)
                for app_label, codename in (
                    permission.split(".")
                    for permission in permissions
                )
            ))
            self.ui_group.permissions.set(list(Permission.objects.filter(permission_filter)))
        else:
            self.ui_group.permissions.clear()
        self.client.force_login(self.ui_user)

    # permissions denied

    def test_user_list_redirect(self):
        self.login_redirect("users")
        self.login()
        self.permission_denied("users")
        self.login("accounts.change_user")
        self.permission_denied("users")

    def test_user_invite_redirect(self):
        self.login_redirect("invite_user")
        self.login()
        self.permission_denied("invite_user")
        self.login("accounts.view_user")
        self.permission_denied("invite_user")

    def test_user_update_redirect(self):
        self.login_redirect("update_user", self.user.id)
        self.login()
        self.permission_denied("update_user", self.superuser.id)
        self.login("accounts.add_user")
        self.permission_denied("update_user", self.superuser.id)

    def test_user_delete_redirect(self):
        self.login_redirect("delete_user", self.user.id)
        self.login()
        self.permission_denied("delete_user", self.user.id)
        self.login("accounts.add_user")
        self.permission_denied("delete_user", self.user.id)

    def test_create_service_account_redirect(self):
        self.login_redirect("create_service_account")
        self.login()
        self.permission_denied("create_service_account")
        self.login("accounts.add_user")
        self.permission_denied("create_service_account")

    def test_create_api_token_redirect(self):
        self.login_redirect("create_user_api_token", self.user.id)

    # user list

    def test_user_list_ok(self):
        self.login("accounts.view_user")
        response = self.client.get(reverse("accounts:users"))
        for text in (self.user.username, self.user.email,
                     self.remoteuser.username, self.remoteuser.email,
                     self.superuser.username, self.superuser.email,
                     "4 Users"):
            self.assertContains(response, text)
        for text in (reverse("accounts:delete_user", args=(self.user.pk,)),
                     reverse("accounts:update_user", args=(self.user.pk,)),
                     reverse("accounts:delete_user", args=(self.remoteuser.pk,)),
                     reverse("accounts:update_user", args=(self.remoteuser.pk,)),
                     reverse("accounts:update_user", args=(self.superuser.pk,))):
            self.assertNotContains(response, text)
        self.assertNotContains(response, reverse("accounts:delete_user", args=(self.superuser.pk,)))
        self.login("accounts.view_user", "accounts.change_user", "accounts.delete_user")
        response = self.client.get(reverse("accounts:users"))
        for text in (reverse("accounts:delete_user", args=(self.user.pk,)),
                     reverse("accounts:update_user", args=(self.user.pk,)),
                     reverse("accounts:delete_user", args=(self.remoteuser.pk,)),
                     reverse("accounts:update_user", args=(self.remoteuser.pk,)),
                     reverse("accounts:update_user", args=(self.superuser.pk,))):
            self.assertContains(response, text)
        self.assertNotContains(response, reverse("accounts:delete_user", args=(self.superuser.pk,)))

    # invite

    def test_user_invite_get(self):
        self.login("accounts.add_user")
        response = self.client.get(reverse("accounts:invite_user"))
        self.assertContains(response, "Send an email invitation")

    def test_user_invite_username_error(self):
        self.login("accounts.add_user")
        response = self.client.post(reverse("accounts:invite_user"),
                                    {"username": self.user.username,
                                     "email": "test@example.com"},
                                    follow=True)
        self.assertFormError(response, "form", "username", "A user with that username already exists.")

    def test_user_invite_email_error(self):
        self.login("accounts.add_user")
        response = self.client.post(reverse("accounts:invite_user"),
                                    {"username": "test",
                                     "email": self.user.email},
                                    follow=True)
        self.assertFormError(response, "form", "email", "User with this Email already exists.")

    def test_user_invite_email_not_allowed(self):
        self.login("accounts.add_user", "accounts.view_user")
        settings._collection["users"] = ConfigDict({"allowed_invitation_domains": ["allowed.example.com"]})
        response = self.client.post(reverse("accounts:invite_user"),
                                    {"username": "test",
                                     "email": "test@example.com"},
                                    follow=True)
        del settings._collection["users"]
        self.assertFormError(response, "form", "email", "Email domain not allowed.")

    def test_user_invite_any_ok(self):
        self.login("accounts.add_user", "accounts.view_user")
        response = self.client.post(reverse("accounts:invite_user"),
                                    {"username": "test",
                                     "email": "test@example.com"},
                                    follow=True)
        for text in ("5 Users", "test", "test@example.com"):
            self.assertContains(response, text)

    def test_user_invite_allowed_ok(self):
        self.login("accounts.add_user", "accounts.view_user")
        settings._collection["users"] = ConfigDict({"allowed_invitation_domains": ["example.com", "example2.com"]})
        response = self.client.post(reverse("accounts:invite_user"),
                                    {"username": "test",
                                     "email": "test@example.com"},
                                    follow=True)
        del settings._collection["users"]
        for text in ("5 Users", "test", "test@example.com"):
            self.assertContains(response, text)

    # create service account

    def test_create_service_account(self):
        self.login("accounts.add_user", "accounts.view_user", "authtoken.add_token")
        username = get_random_string()
        response = self.client.post(reverse("accounts:create_service_account"),
                                    {"username": username},
                                    follow=True)
        self.assertTemplateUsed(response, "accounts/user_api_token.html")
        service_account = response.context["object"]
        self.assertEqual(service_account.username, username)
        self.assertTrue(service_account.is_service_account)
        token = service_account.auth_token
        self.assertContains(response, token.key)

    # update

    def test_user_update_404(self):
        self.login("accounts.change_user")
        response = self.client.get(reverse("accounts:update_user", args=(0,)))
        self.assertEqual(response.status_code, 404)

    def test_user_update_get(self):
        self.login("accounts.change_user")
        for user, ue_disabled, su_disabled in ((self.user, False, False),
                                               (self.remoteuser, True, False),
                                               (self.superuser, False, True)):
            response = self.client.get(reverse("accounts:update_user", args=(user.id,)))
            self.assertContains(response, f"Update user {user}")
            form = response.context["form"]
            if ue_disabled:
                self.assertNotIn("username", form.fields)
                self.assertNotIn("email", form.fields)
            else:
                self.assertIn("username", form.fields)
                self.assertIn("email", form.fields)

    def test_user_update_username_error(self):
        self.login("accounts.change_user")
        response = self.client.post(reverse("accounts:update_user", args=(self.user.id,)),
                                    {"username": self.superuser.username,
                                     "email": self.user.email,
                                     "is_superuser": self.user.is_superuser})
        self.assertFormError(response, "form", "username", "A user with that username already exists.")

    def test_user_update_email_error(self):
        self.login("accounts.change_user")
        response = self.client.post(reverse("accounts:update_user", args=(self.user.id,)),
                                    {"username": self.user.username,
                                     "email": self.superuser.email,
                                     "is_superuser": self.user.is_superuser})
        self.assertFormError(response, "form", "email", "User with this Email already exists.")

    def test_user_update_ok(self):
        self.login("accounts.change_user", "accounts.view_user")
        response = self.client.post(reverse("accounts:update_user", args=(self.user.id,)),
                                    {"username": "toto",
                                     "email": "tata@example.com",
                                     "is_superuser": self.user.is_superuser},
                                    follow=True)
        self.assertTemplateUsed(response, "accounts/user_detail.html")
        for text in ("User tata@example.com", "toto"):
            self.assertContains(response, text)

    # delete

    def test_user_delete_404(self):
        self.login("accounts.delete_user")
        response = self.client.post(reverse("accounts:delete_user", args=(0,)))
        self.assertEqual(response.status_code, 404)

    def test_superuser_delete_redirect(self):
        self.login("accounts.delete_user", "accounts.view_user")
        response = self.client.post(reverse("accounts:delete_user", args=(self.superuser.id,)))
        self.assertRedirects(response, reverse("accounts:users"))

    def test_user_delete_ok(self):
        self.login("accounts.delete_user", "accounts.view_user")
        user_str = str(self.user)
        response = self.client.post(reverse("accounts:delete_user", args=(self.user.id,)),
                                    follow=True)
        self.assertContains(response, f"User {user_str} deleted")
        self.assertTemplateUsed(response, "accounts/user_list.html")
        self.assertContains(response, "3 User")

    # token

    def test_create_api_token_not_self(self):
        self.login()
        # ui_user != user → 403
        response = self.client.post(reverse("accounts:create_user_api_token", args=(self.user.id,)),
                                    follow=True)
        self.assertEqual(response.status_code, 403)

    def test_create_api_token_no_perms(self):
        service_account = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
            is_service_account=True,
        )

        self.login()
        # service account OK, but without the required permissions
        response = self.client.post(reverse("accounts:create_user_api_token", args=(service_account.id,)),
                                    follow=True)
        self.assertEqual(response.status_code, 403)

    def test_self_create_api_token(self):
        self.login()
        response = self.client.post(reverse("accounts:create_user_api_token", args=(self.ui_user.id,)),
                                    follow=True)
        self.assertTemplateUsed(response, "accounts/user_api_token.html")
        user = response.context["object"]
        self.assertEqual(user, self.ui_user)
        token = user.auth_token
        self.assertContains(response, token.key)
        self.assertContains(response, "Settings")
        self.assertNotContains(response, "Users")

    def test_server_account_create_api_token(self):
        service_account = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
            is_service_account=True,
        )

        self.login("accounts.view_user", "authtoken.add_token")
        response = self.client.post(reverse("accounts:create_user_api_token", args=(service_account.id,)),
                                    follow=True)
        self.assertTemplateUsed(response, "accounts/user_api_token.html")
        user = response.context["object"]
        self.assertEqual(user, service_account)
        token = service_account.auth_token
        self.assertContains(response, token.key)
        self.assertNotContains(response, "Settings")
        self.assertContains(response, "Users")

    def test_delete_api_token_not_self(self):
        self.login()
        # ui_user != user → 403
        response = self.client.post(reverse("accounts:delete_user_api_token", args=(self.user.id,)),
                                    follow=True)
        self.assertEqual(response.status_code, 403)

    def test_delete_api_token_no_perms(self):
        service_account = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
            is_service_account=True,
        )

        self.login()
        # service account OK, but without the required permissions
        response = self.client.post(reverse("accounts:delete_user_api_token", args=(service_account.id,)),
                                    follow=True)
        self.assertEqual(response.status_code, 403)

    def test_delete_api_token_self(self):
        self.login()
        token, _ = Token.objects.get_or_create(user=self.ui_user)
        response = self.client.post(reverse("accounts:delete_user_api_token", args=(self.ui_user.id,)),
                                    follow=True)
        self.assertTemplateUsed(response, "accounts/profile.html")
        self.assertEqual(Token.objects.filter(user=self.ui_user).count(), 0)

    def test_delete_service_account_api_token(self):
        service_account = User.objects.create_user(
            get_random_string(19),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
            is_service_account=True,
        )

        token, _ = Token.objects.get_or_create(user=service_account)
        self.login("accounts.view_user", "authtoken.delete_token")
        response = self.client.post(reverse("accounts:delete_user_api_token", args=(service_account.id,)),
                                    follow=True)
        self.assertTemplateUsed(response, "accounts/user_detail.html")
        self.assertEqual(response.context["object"], service_account)
        self.assertEqual(Token.objects.filter(user=service_account).count(), 0)
