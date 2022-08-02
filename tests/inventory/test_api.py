from functools import reduce
import operator
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.urls import reverse
from django.utils.crypto import get_random_string
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from accounts.models import User
from zentral.contrib.inventory.models import MetaBusinessUnit, Tag


class InventoryAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            get_random_string(),
            f"{get_random_string()}@zentral.io",
            get_random_string(),
        )

        cls.group = Group.objects.create(name=get_random_string())
        cls.user.groups.set([cls.group])
        cls.token, _ = Token.objects.get_or_create(user=cls.user)

    def setUp(self):
        super().setUp()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def _set_permissions(self, *permissions):
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

    # machines export

    def test_export_machines_unauthorized(self):
        response = self.client.post(reverse('inventory_api:machines_export'))
        self.assertEqual(response.status_code, 403)

    def test_export_machines(self):
        self._set_permissions("inventory.view_machinesnapshot")
        response = self.client.post(reverse('inventory_api:machines_export'))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("task_id", response.data)
        self.assertIn("task_result_url", response.data)

    # macos apps export

    def test_export_macos_apps_unauthorized(self):
        response = self.client.post(reverse('inventory_api:macos_apps_export'))
        self.assertEqual(response.status_code, 403)

    def test_export_macos_apps(self):
        self._set_permissions("inventory.view_osxapp", "inventory.view_osxappinstance")
        response = self.client.post(reverse('inventory_api:macos_apps_export'))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("task_id", response.data)
        self.assertIn("task_result_url", response.data)

    # create meta business unit

    def test_create_meta_business_unit_unauthorized(self):
        data = {'name': 'TestMBU0'}
        response = self.client.post(reverse('inventory_api:meta_business_units'), data, format='json')
        self.assertEqual(response.status_code, 403)

    def test_create_meta_business_unit(self):
        data = {'name': 'TestMBU0'}
        self._set_permissions("inventory.add_metabusinessunit")
        response = self.client.post(reverse('inventory_api:meta_business_units'), data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MetaBusinessUnit.objects.filter(name='TestMBU0').count(), 1)
        meta_business_unit = MetaBusinessUnit.objects.get(name='TestMBU0')
        self.assertEqual(meta_business_unit.name, 'TestMBU0')
        self.assertFalse(meta_business_unit.api_enrollment_enabled())

    def test_create_api_enabled_meta_business_unit(self):
        url = reverse('inventory_api:meta_business_units')
        data = {'name': 'TestMBU1', 'api_enrollment_enabled': True}
        self._set_permissions("inventory.add_metabusinessunit")
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MetaBusinessUnit.objects.filter(name='TestMBU1').count(), 1)
        meta_business_unit = MetaBusinessUnit.objects.get(name='TestMBU1')
        self.assertEqual(meta_business_unit.name, 'TestMBU1')
        self.assertTrue(meta_business_unit.api_enrollment_enabled())

    # get meta business unit

    def test_get_meta_business_unit_unauthorized(self):
        meta_business_unit = MetaBusinessUnit.objects.create(name=get_random_string())
        response = self.client.get(reverse('inventory_api:meta_business_unit', args=(meta_business_unit.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_get_meta_business_unit(self):
        meta_business_unit = MetaBusinessUnit.objects.create(name=get_random_string())
        self._set_permissions("inventory.view_metabusinessunit")
        response = self.client.get(reverse('inventory_api:meta_business_unit', args=(meta_business_unit.pk,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data,
                         {'id': meta_business_unit.pk,
                          'name': meta_business_unit.name,
                          'api_enrollment_enabled': meta_business_unit.api_enrollment_enabled()})

    # update meta business unit

    def test_update_meta_business_unit_unauthorized(self):
        meta_business_unit = MetaBusinessUnit.objects.create(name=get_random_string())
        response = self.client.put(reverse('inventory_api:meta_business_unit', args=(meta_business_unit.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_update_meta_business_unit(self):
        meta_business_unit = MetaBusinessUnit.objects.create(name=get_random_string())
        self.assertFalse(meta_business_unit.api_enrollment_enabled())
        self._set_permissions("inventory.change_metabusinessunit")
        url = reverse('inventory_api:meta_business_unit', args=(meta_business_unit.pk,))
        updated_name = get_random_string()
        data = {'name': updated_name, 'api_enrollment_enabled': True}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        meta_business_unit.refresh_from_db()
        self.assertEqual(meta_business_unit.name, updated_name)
        self.assertTrue(meta_business_unit.api_enrollment_enabled())
        data = {"name": updated_name, 'api_enrollment_enabled': False}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data,
                         {"api_enrollment_enabled": [
                              "Cannot disable API enrollment"
                          ]})

    # list meta business unit

    def test_list_meta_business_unit_unauthorized(self):
        response = self.client.get(reverse('inventory_api:meta_business_units'))
        self.assertEqual(response.status_code, 403)

    def test_list_meta_business_unit(self):
        meta_business_unit = MetaBusinessUnit.objects.create(name=get_random_string())
        url = reverse('inventory_api:meta_business_units')
        self._set_permissions("inventory.view_metabusinessunit")
        response = self.client.get(url, {"name": meta_business_unit.name})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data,
                         [{"id": meta_business_unit.pk,
                           "name": meta_business_unit.name,
                           "api_enrollment_enabled": meta_business_unit.api_enrollment_enabled()}])

    # list tag

    def test_list_tag_unauthorized(self):
        response = self.client.get(reverse('inventory_api:tags'))
        self.assertEqual(response.status_code, 403)

    def test_list_tag(self):
        tag = Tag.objects.create(name=get_random_string())
        self._set_permissions("inventory.view_tag")
        response = self.client.get(reverse('inventory_api:tags'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["id"], tag.pk)
        self.assertEqual(response.data[0]["name"], tag.name)

    # tag

    def test_tag_unauthorized(self):
        tag = Tag.objects.create(name=get_random_string())
        response = self.client.get(reverse('inventory_api:tag', args=(tag.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_tag(self):
        tag = Tag.objects.create(name=get_random_string())
        self._set_permissions("inventory.view_tag")
        response = self.client.get(reverse('inventory_api:tag', args=(tag.pk,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], tag.pk)
        self.assertEqual(response.data["name"], tag.name)
