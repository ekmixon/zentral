from functools import reduce
import json
import operator
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.test import TestCase, override_settings
from zentral.contrib.inventory.models import EnrollmentSecret, MetaBusinessUnit
from zentral.contrib.munki.models import Configuration, Enrollment
from accounts.models import User


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class MunkiSetupViewsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # user
        cls.user = User.objects.create_user("godzilla", "godzilla@zentral.io", get_random_string())
        cls.group = Group.objects.create(name=get_random_string())
        cls.user.groups.set([cls.group])
        # mbu
        cls.mbu = MetaBusinessUnit.objects.create(name=get_random_string(64))
        cls.mbu.create_enrollment_business_unit()

    # utility methods

    def _login_redirect(self, url):
        response = self.client.get(url)
        self.assertRedirects(response, "{u}?next={n}".format(u=reverse("login"), n=url))

    def _login(self, *permissions):
        if permissions:
            permission_filter = reduce(operator.or_, (
                Q(content_type__app_label=app_label, codename=codename)
                for app_label, codename in (
                    permission.split(".")
                    for permission in permissions
                )
            ))
            self.group.permissions.set(list(Permission.objects.filter(permission_filter)))
        else:
            self.group.permissions.clear()
        self.client.force_login(self.user)

    def _post_as_json(self, url_name, data):
        return self.client.post(
            reverse(f"munki:{url_name}"),
            json.dumps(data),
            content_type="application/json",
        )

    def _force_configuration(self):
        return Configuration.objects.create(name=get_random_string())

    def _force_enrollment(self):
        enrollment_secret = EnrollmentSecret.objects.create(meta_business_unit=self.mbu)
        return Enrollment.objects.create(configuration=self._force_configuration(), secret=enrollment_secret)

    # configurations

    def test_configurations_redirect(self):
        self._login_redirect(reverse("munki:configurations"))

    def test_configurations_permission_denied(self):
        self._login()
        response = self.client.get(reverse("munki:configurations"))
        self.assertEqual(response.status_code, 403)

    def test_configurations(self):
        self._login("munki.view_configuration")
        response = self.client.get(reverse("munki:configurations"))
        self.assertEqual(response.status_code, 200)

    # create configuration

    def test_create_configuration_redirect(self):
        self._login_redirect(reverse("munki:create_configuration"))

    def test_create_configuration_permission_denied(self):
        self._login()
        response = self.client.get(reverse("munki:create_configuration"))
        self.assertEqual(response.status_code, 403)

    def test_create_configuration_get(self):
        self._login("munki.add_configuration")
        response = self.client.get(reverse("munki:create_configuration"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "munki/configuration_form.html")

    def test_create_configuration_post(self):
        self._login("munki.add_configuration", "munki.view_configuration")
        name = get_random_string()
        response = self.client.post(reverse("munki:create_configuration"),
                                    {"name": name,
                                     "inventory_apps_full_info_shard": 17,
                                     "principal_user_detection_sources": "logged_in_user",
                                     "principal_user_detection_domains": "yolo.fr"},
                                    follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "munki/configuration_detail.html")
        self.assertContains(response, name)

    # update configuration

    def test_update_configuration_redirect(self):
        configuration = self._force_configuration()
        self._login_redirect(reverse("munki:update_configuration", args=(configuration.pk,)))

    def test_update_configuration_permission_denied(self):
        configuration = self._force_configuration()
        self._login()
        response = self.client.get(reverse("munki:update_configuration", args=(configuration.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_update_configuration_get(self):
        configuration = self._force_configuration()
        self._login("munki.change_configuration")
        response = self.client.get(reverse("munki:update_configuration", args=(configuration.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "munki/configuration_form.html")

    def test_update_configuration_post(self):
        configuration = self._force_configuration()
        self._login("munki.change_configuration", "munki.view_configuration")
        response = self.client.post(reverse("munki:update_configuration", args=(configuration.pk,)),
                                    {"name": configuration.name,
                                     "inventory_apps_full_info_shard": 17,
                                     "principal_user_detection_sources": "logged_in_user",
                                     "principal_user_detection_domains": "yolo.fr"},
                                    follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "munki/configuration_detail.html")
        configuration2 = response.context["object"]
        self.assertEqual(configuration2, configuration)
        self.assertEqual(configuration2.inventory_apps_full_info_shard, 17)
        self.assertEqual(configuration2.principal_user_detection_sources, ["logged_in_user"])
        self.assertEqual(configuration2.principal_user_detection_domains, ["yolo.fr"])

    # create enrollment

    def test_create_enrollment_redirect(self):
        configuration = self._force_configuration()
        self._login_redirect(reverse("munki:create_enrollment", args=(configuration.pk,)))

    def test_create_enrollment_permission_denied(self):
        configuration = self._force_configuration()
        self._login()
        response = self.client.get(reverse("munki:create_enrollment", args=(configuration.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_create_enrollment_get(self):
        configuration = self._force_configuration()
        self._login("munki.add_enrollment")
        response = self.client.get(reverse("munki:create_enrollment", args=(configuration.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "munki/enrollment_form.html")
        self.assertContains(response, "Munki enrollment")

    def test_create_enrollment_post(self):
        configuration = self._force_configuration()
        self._login("munki.add_enrollment", "munki.view_configuration", "munki.view_enrollment")
        response = self.client.post(reverse("munki:create_enrollment", args=(configuration.pk,)),
                                    {"configuration": configuration.pk,
                                     "secret-meta_business_unit": self.mbu.pk}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "munki/configuration_detail.html")
        enrollment = response.context["enrollments"][0][0]
        self.assertEqual(enrollment.configuration, configuration)
        self.assertEqual(enrollment.secret.meta_business_unit, self.mbu)
        self.assertContains(response, enrollment.secret.meta_business_unit.name)

    # enrollment package

    def test_enrollment_package_redirect(self):
        enrollment = self._force_enrollment()
        self._login_redirect(reverse("munki:enrollment_package", args=(enrollment.configuration.pk, enrollment.pk,)))

    def test_enrollment_package_permission_denied(self):
        enrollment = self._force_enrollment()
        self._login()
        response = self.client.get(reverse("munki:enrollment_package",
                                           args=(enrollment.configuration.pk, enrollment.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_enrollment_package(self):
        enrollment = self._force_enrollment()
        self._login("munki.view_enrollment")
        response = self.client.get(reverse("munki:enrollment_package",
                                           args=(enrollment.configuration.pk, enrollment.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], "application/octet-stream")
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="zentral_munki_enroll.pkg"')
