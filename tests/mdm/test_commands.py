import copy
import plistlib
import uuid
from datetime import datetime
from django.http import HttpResponse
from django.test import TestCase
from django.utils.crypto import get_random_string
from zentral.contrib.inventory.models import EnrollmentSecret, MetaBusinessUnit
from zentral.contrib.mdm.models import (Artifact, ArtifactType, ArtifactVersion,
                                        Blueprint, BlueprintArtifact,
                                        Channel, DeviceArtifact,
                                        DEPEnrollment, DEPEnrollmentSession,
                                        DEPOrganization, DEPToken, DEPVirtualServer,
                                        EnrolledDevice, EnrolledUser,
                                        Platform, Profile, PushCertificate,
                                        UserArtifact)
from zentral.contrib.mdm.commands.device_configured import DeviceConfigured
from zentral.contrib.mdm.commands.device_information import DeviceInformation
from zentral.contrib.mdm.commands.install_profile import InstallProfile
from zentral.contrib.mdm.commands.remove_profile import RemoveProfile
from zentral.contrib.mdm.commands.utils import (_finish_dep_enrollment_configuration,
                                                _install_artifacts,
                                                _get_next_queued_command,
                                                _remove_artifacts)


PROFILE_TEMPLATE = {
    'PayloadContent': [{
        'PayloadType': 'com.apple.dock',
        'PayloadDescription': 'Dock Payload',
        'PayloadDisplayName': 'Dock',
        'PayloadVersion': 1,
        'orientation': 'right'
    }],
    'PayloadType': 'Configuration',
    'PayloadDescription': 'Superbe profile imbattable!!!',
    'PayloadDisplayName': 'Test User Profile with Dock',
    'PayloadVersion': 1,
    'PayloadOrganization': 'Zentral',
    'PayloadScope': 'User',
}


def build_profile(
    payload_display_name=None,
    payload_description=None,
    payload_identifier=None,
    payload_uuid=None,
    channel=Channel.Device
):
    if payload_uuid is None:
        payload_uuid = str(uuid.uuid4()).upper()
    if payload_identifier is None:
        payload_identifier = f"io.zentral.test.{payload_uuid}"
    profile = copy.deepcopy(PROFILE_TEMPLATE)
    profile["PayloadIdentifier"] = payload_identifier
    profile["PayloadUUID"] = payload_uuid
    profile["PayloadDisplayName"] = payload_display_name or get_random_string(16)
    profile["PayloadDescription"] = payload_description or get_random_string(32)
    profile["PayloadScope"] = "System" if channel == Channel.Device else "User"
    payload = profile["PayloadContent"][0]
    payload["PayloadIdentifier"] = f"{payload_identifier}.0"
    payload["PayloadUUID"] = str(uuid.uuid4()).upper()
    return plistlib.dumps(profile)


class TestMDMCommands(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.meta_business_unit = MetaBusinessUnit.objects.create(name=get_random_string(32))
        push_certificate = PushCertificate.objects.create(
            name=get_random_string(64),
            topic=get_random_string(256),
            not_before=datetime(2000, 1, 1),
            not_after=datetime(2050, 1, 1),
            certificate=get_random_string(64).encode("utf-8"),
            private_key=get_random_string(64).encode("utf-8")
        )
        cls.blueprint1 = Blueprint.objects.create(name=get_random_string(32))

        # Enrolled devices / user
        cls.enrolled_device_no_blueprint = EnrolledDevice.objects.create(
            push_certificate=push_certificate,
            serial_number=get_random_string(64),
            platform="macOS",
            udid=get_random_string(36),
            token=get_random_string(32).encode("utf-8"),
            push_magic=get_random_string(73),
            unlock_token=get_random_string(32).encode("utf-8")
        )
        cls.enrolled_device = EnrolledDevice.objects.create(
            push_certificate=push_certificate,
            serial_number=get_random_string(64),
            platform="macOS",
            blueprint=cls.blueprint1,
            udid=get_random_string(36),
            token=get_random_string(32).encode("utf-8"),
            push_magic=get_random_string(73),
            unlock_token=get_random_string(32).encode("utf-8")
        )
        cls.enrolled_user = EnrolledUser.objects.create(
            enrolled_device=cls.enrolled_device,
            user_id=str(uuid.uuid4()).upper(),
            long_name=get_random_string(),
            short_name=get_random_string(),
            token=get_random_string().encode("utf-8"),
        )
        cls.enrolled_device_awaiting_configuration = EnrolledDevice.objects.create(
            push_certificate=push_certificate,
            serial_number=get_random_string(64),
            platform="macOS",
            blueprint=cls.blueprint1,
            awaiting_configuration=True,
            udid=get_random_string(36),
            token=get_random_string(32).encode("utf-8"),
            push_magic=get_random_string(73),
            unlock_token=get_random_string(32).encode("utf-8")
        )

        # DEP enrollment
        dep_organization = DEPOrganization.objects.create(
            identifier=get_random_string(128),
            admin_id=f"{get_random_string()}@zentral.io",
            name=get_random_string(),
            email=f"{get_random_string()}@zentral.io",
            phone=get_random_string(),
            address=get_random_string(),
            type=DEPOrganization.ORG,
            version=DEPOrganization.V2,
        )

        dep_token = DEPToken.objects.create(
            certificate=get_random_string().encode("utf-8"),
            private_key=get_random_string().encode("utf-8"),
        )
        dep_virtual_server = DEPVirtualServer.objects.create(
            name=get_random_string(),
            uuid=uuid.uuid4(),
            organization=dep_organization,
            token=dep_token
        )
        dep_enrollment = DEPEnrollment.objects.create(
            uuid=uuid.uuid4(),
            virtual_server=dep_virtual_server,
            push_certificate=push_certificate,
            blueprint=cls.blueprint1,
            enrollment_secret=EnrollmentSecret.objects.create(meta_business_unit=cls.meta_business_unit),
            skip_setup_items=[p for p, _ in DEPEnrollment.SKIPPABLE_SETUP_PANE_CHOICES],
            name=get_random_string()
        )
        cls.dep_enrollment_session = DEPEnrollmentSession.objects.create_from_dep_enrollment(
            dep_enrollment, cls.enrolled_device.serial_number, cls.enrolled_device.udid
        )
        es_request = EnrollmentSecret.objects.verify(
            "dep_enrollment_session",
            cls.dep_enrollment_session.enrollment_secret.secret,
            user_agent=get_random_string(), public_ip_address="127.0.0.1"
        )
        cls.dep_enrollment_session.set_scep_verified_status(es_request)
        cls.dep_enrollment_session.set_authenticated_status(cls.enrolled_device)
        cls.dep_enrollment_session.set_completed_status(cls.enrolled_device)

    def _force_artifact(
        self,
        version_count=1,
        artifact_type=ArtifactType.Profile,
        channel=Channel.Device,
        platforms=None,
        install_before_setup_assistant=False,
        auto_update=True,
        priority=0
    ):
        if platforms is None:
            platforms = Platform.all_values()
        artifact = Artifact.objects.create(
            name=get_random_string(32),
            type=artifact_type.name,
            channel=channel.name,
            platforms=platforms
        )
        artifact_versions = []
        payload_identifier = (
            f"{get_random_string(2)}.{get_random_string(4)}.{str(uuid.uuid4())}"
        )

        payload_identifier = None
        for version in range(version_count, 0, -1):
            artifact_version = ArtifactVersion.objects.create(artifact=artifact, version=version)
            artifact_versions.append(artifact_version)
            if artifact_type == ArtifactType.Profile:
                if payload_identifier is None:
                    payload_identifier = f"{get_random_string(2)}.{get_random_string(4)}.{str(uuid.uuid4()).upper()}"

                payload_uuid = str(uuid.uuid4()).upper()
                payload_display_name = get_random_string(16)
                payload_description = get_random_string(32)
                Profile.objects.create(
                    artifact_version=artifact_version,
                    source=build_profile(
                        payload_display_name=payload_display_name,
                        payload_description=payload_description,
                        payload_identifier=payload_identifier,
                        payload_uuid=payload_uuid,
                        channel=channel
                    ),
                    payload_identifier=payload_identifier,
                    payload_uuid=payload_uuid,
                    payload_display_name=payload_display_name,
                    payload_description=payload_description
                )
        return artifact, artifact_versions

    def _force_blueprint_artifact(
        self,
        version_count=1,
        artifact_type=ArtifactType.Profile,
        channel=Channel.Device,
        platforms=None,
        install_before_setup_assistant=False,
        auto_update=True,
        priority=0,
        blueprint=None
    ):
        artifact, artifact_versions = self._force_artifact(
            version_count,
            artifact_type,
            channel,
            platforms,
            install_before_setup_assistant,
            auto_update,
            priority
        )
        BlueprintArtifact.objects.create(
            blueprint=blueprint or self.blueprint1,
            artifact=artifact,
            install_before_setup_assistant=install_before_setup_assistant,
            auto_update=auto_update,
            priority=priority,
        )
        return artifact, artifact_versions

    def _force_target_artifact_version(self, target, artifact_version):
        kwargs = {"artifact_version__artifact": artifact_version.artifact,
                  "defaults": {"artifact_version": artifact_version}}
        if isinstance(target, EnrolledDevice):
            model = DeviceArtifact
            kwargs["enrolled_device"] = target
        else:
            model = UserArtifact
            kwargs["enrolled_user"] = target
        return model.objects.update_or_create(**kwargs)[0]

    def test_no_next_queues_command(self):
        self.assertIsNone(_get_next_queued_command(
                Channel.Device,
                self.dep_enrollment_session,
                self.enrolled_device,
                None
        ))

    def test_device_information(self):
        command = DeviceInformation.create_for_device(self.enrolled_device)
        self.assertEqual(command.enrolled_device, self.enrolled_device)
        self.assertIsNotNone(command.db_command.time)
        self.assertIsNone(_get_next_queued_command(
                Channel.Device,
                self.dep_enrollment_session,
                self.enrolled_device,
                None
        ))

    def test_queue_device_information(self):
        command = DeviceInformation.create_for_device(self.enrolled_device, queue=True)
        self.assertIsNone(command.db_command.time)
        fetched_command = _get_next_queued_command(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        )
        self.assertEqual(command, fetched_command)
        self.assertIsNone(_get_next_queued_command(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device_no_blueprint,
            None
        ))
        self.assertIsNone(_get_next_queued_command(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        ))

    def test_device_configured(self):
        self.enrolled_device_awaiting_configuration.refresh_from_db()
        self.assertIsNone(_finish_dep_enrollment_configuration(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))
        command = _finish_dep_enrollment_configuration(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device_awaiting_configuration,
            None
        )
        self.assertIsInstance(command, DeviceConfigured)
        self.assertEqual(command.channel, Channel.Device)
        self.assertIsNotNone(command.db_command.time)
        self.assertIsNone(command.db_command.result_time)
        self.assertTrue(self.enrolled_device_awaiting_configuration.awaiting_configuration)
        command.process_response({"Status": "Acknowledged"}, self.dep_enrollment_session, self.meta_business_unit)
        command.db_command.refresh_from_db()
        self.assertEqual(command.db_command.status, "Acknowledged")
        self.assertIsNotNone(command.db_command.result_time)
        self.enrolled_device_awaiting_configuration.refresh_from_db()
        self.assertFalse(self.enrolled_device_awaiting_configuration.awaiting_configuration)

    def test_no_device_profile(self):
        self.assertIsNone(_install_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))

    def test_install_device_profile(self):
        artifact, artifact_versions = self._force_blueprint_artifact()
        command = _install_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        )
        self.assertIsInstance(command, InstallProfile)
        self.assertEqual(command.channel, Channel.Device)
        self.assertEqual(command.db_command.artifact_version, artifact_versions[0])
        http_response = command.build_http_response(self.dep_enrollment_session)
        self.assertIsInstance(http_response, HttpResponse)
        self.assertIsNone(_install_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        ))
        qs = DeviceArtifact.objects.filter(enrolled_device=self.enrolled_device)
        self.assertEqual(qs.count(), 0)
        command.process_response({"Status": "Acknowledged"}, self.dep_enrollment_session, self.meta_business_unit)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.filter(artifact_version=artifact_versions[0]).count(), 1)

    def test_no_install_device_profile_previous_error(self):
        artifact, artifact_versions = self._force_blueprint_artifact()
        command = _install_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        )
        command.process_response({"Status": "Error", "ErrorChain": [{"un": 1}]},
                                 self.dep_enrollment_session, self.meta_business_unit)
        self.assertIsNone(_install_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))

    def test_install_user_profile(self):
        artifact, artifact_versions = self._force_blueprint_artifact(channel=Channel.User)
        command = _install_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        )
        self.assertIsInstance(command, InstallProfile)
        self.assertEqual(command.channel, Channel.User)
        self.assertEqual(command.db_command.artifact_version, artifact_versions[0])
        http_response = command.build_http_response(self.dep_enrollment_session)
        self.assertIsInstance(http_response, HttpResponse)
        self.assertIsNone(_install_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))
        qs = UserArtifact.objects.filter(enrolled_user=self.enrolled_user)
        self.assertEqual(qs.count(), 0)
        command.process_response({"Status": "Acknowledged"}, self.dep_enrollment_session, self.meta_business_unit)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.filter(artifact_version=artifact_versions[0]).count(), 1)

    def test_no_install_user_profile_previous_error(self):
        artifact, artifact_versions = self._force_blueprint_artifact(channel=Channel.User)
        command = _install_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        )
        command.process_response({"Status": "Error", "ErrorChain": [{"un": 1}]},
                                 self.dep_enrollment_session, self.meta_business_unit)
        self.assertIsNone(_install_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        ))

    def test_remove_device_profile(self):
        artifact, artifact_versions = self._force_artifact()
        self.assertIsNone(_remove_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))
        device_artifact = self._force_target_artifact_version(self.enrolled_device, artifact_versions[0])
        command = _remove_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        )
        self.assertIsInstance(command, RemoveProfile)
        self.assertEqual(command.channel, Channel.Device)
        self.assertEqual(command.db_command.artifact_version, artifact_versions[0])
        http_response = command.build_http_response(self.dep_enrollment_session)
        self.assertIsInstance(http_response, HttpResponse)
        self.assertIsNone(_remove_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        ))
        qs = DeviceArtifact.objects.filter(enrolled_device=self.enrolled_device)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first(), device_artifact)
        command.process_response({"Status": "Acknowledged"}, self.dep_enrollment_session, self.meta_business_unit)
        self.assertEqual(qs.count(), 0)

    def test_no_remove_device_profile_previous_error(self):
        artifact, artifact_versions = self._force_artifact()
        self._force_target_artifact_version(self.enrolled_device, artifact_versions[0])
        command = _remove_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        )
        command.process_response({"Status": "Error", "ErrorChain": [{"un": 1}]},
                                 self.dep_enrollment_session, self.meta_business_unit)
        self.assertIsNone(_remove_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))

    def test_remove_user_profile(self):
        artifact, artifact_versions = self._force_artifact()
        self.assertIsNone(_remove_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        ))
        user_artifact = self._force_target_artifact_version(self.enrolled_user, artifact_versions[0])
        command = _remove_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        )
        self.assertIsInstance(command, RemoveProfile)
        self.assertEqual(command.channel, Channel.User)
        self.assertEqual(command.db_command.artifact_version, artifact_versions[0])
        http_response = command.build_http_response(self.dep_enrollment_session)
        self.assertIsInstance(http_response, HttpResponse)
        self.assertIsNone(_remove_artifacts(
            Channel.Device,
            self.dep_enrollment_session,
            self.enrolled_device,
            None
        ))
        qs = UserArtifact.objects.filter(enrolled_user=self.enrolled_user)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first(), user_artifact)
        command.process_response({"Status": "Acknowledged"}, self.dep_enrollment_session, self.meta_business_unit)
        self.assertEqual(qs.count(), 0)

    def test_no_remove_user_profile_previous_error(self):
        artifact, artifact_versions = self._force_artifact()
        self._force_target_artifact_version(self.enrolled_user, artifact_versions[0])
        command = _remove_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        )
        command.process_response({"Status": "Error", "ErrorChain": [{"un": 1}]},
                                 self.dep_enrollment_session, self.meta_business_unit)
        self.assertIsNone(_remove_artifacts(
            Channel.User,
            self.dep_enrollment_session,
            self.enrolled_device,
            self.enrolled_user
        ))
