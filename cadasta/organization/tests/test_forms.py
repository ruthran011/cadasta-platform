import os
from pytest import raises

from django.test import TestCase
from django.conf import settings

from buckets.test.utils import ensure_dirs
from buckets.test.storage import FakeS3Storage

from .. import forms
from ..models import Organization, OrganizationRole, ProjectRole
from .factories import OrganizationFactory, ProjectFactory

from core.tests.factories import PolicyFactory, RoleFactory
from questionnaires.tests.factories import QuestionnaireFactory
from questionnaires.exceptions import InvalidXLSForm
from accounts.tests.factories import UserFactory


class OrganzationAddTest(TestCase):
    def setUp(self):
        self.data = {
            'name': 'Org',
            'description': 'Org description',
            'urls': '',
            'contacts-TOTAL_FORMS': 1,
            'contacts-INITIAL_FORMS': 0,
            'contacts-MIN_NUM_FORMS': 0,
            'contacts-MAX_NUM_FORMS': 1000,
            'contacts-0-name': '',
            'contacts-0-email': '',
            'contacts-0-tel': ''
        }

    def _save(self, data, count=1):
        form = forms.OrganizationForm(data, user=UserFactory.create())
        form.save()
        assert form.is_valid() is True
        assert Organization.objects.count() == count

    def test_add_organization(self):
        self._save(self.data)
        org = Organization.objects.first()

        assert org.slug == 'org'
        assert OrganizationRole.objects.filter(organization=org).count() == 1

    def test_unique_slugs(self):
        self.data['description'] = 'Org description #1'
        self._save(self.data)
        org1 = Organization.objects.first()
        assert org1.slug == 'org'

        self.data['description'] = 'Org description #2'
        self._save(self.data, count=2)
        orgs = Organization.objects.all()
        assert len(orgs) == 2
        assert orgs[0].slug != orgs[1].slug

    def test_add_organization_with_url(self):
        self.data['urls'] = 'http://example.com'
        self._save(self.data)
        org = Organization.objects.first()
        assert org.urls == ['http://example.com']

    def test_add_organization_with_contact(self):
        self.data['contacts-0-name'] = 'Ringo Starr'
        self.data['contacts-0-email'] = 'ringo@beatles.uk'
        self.data['contacts-0-tel'] = '555-5555'
        self._save(self.data)
        org = Organization.objects.first()
        assert org.contacts == [{
            'name': 'Ringo Starr',
            'tel': '555-5555',
            'email': 'ringo@beatles.uk'
        }]

    def test_update_organization(self):
        org = OrganizationFactory.create(slug='some-org')
        self.data['description'] = 'Org description'
        form = forms.OrganizationForm(self.data, instance=org)
        form.save()

        org.refresh_from_db()

        assert form.is_valid() is True
        assert org.name == self.data['name']
        assert org.description == self.data['description']
        assert org.slug == 'some-org'


class AddOrganizationMemberFormTest(TestCase):
    def _save(self, identifier=None, identifier_field=None, ok=True):
        org = OrganizationFactory.create()
        user = UserFactory.create()
        if identifier_field is not None:
            identifier = getattr(user, identifier_field)
        data = {'identifier': identifier}
        form = forms.AddOrganizationMemberForm(data, organization=org)
        if ok:
            form.save()
            assert form.is_valid() is True
            assert OrganizationRole.objects.filter(
                organization=org, user=user).count() == 1
        else:
            with raises(ValueError):
                form.save()
            assert form.is_valid() is False
            assert OrganizationRole.objects.count() == 0

    def test_add_with_username(self):
        self._save(identifier_field='username')

    def test_add_with_email(self):
        self._save(identifier_field='email')

    def test_add_non_existing_user(self):
        self._save(identifier='some-user', ok=False)


class EditOrganizationMemberFormTest(TestCase):
    def test_edit_org_role(self):
        org = OrganizationFactory.create()
        user = UserFactory.create()

        data = {'org_role': 'A'}

        org_role = OrganizationRole.objects.create(organization=org, user=user)
        form = forms.EditOrganizationMemberForm(data, org, user)

        form.save()
        org_role.refresh_from_db()

        assert form.is_valid() is True
        assert org_role.admin is True

    def test_edit_project_roles(self):
        user = UserFactory.create()
        org = OrganizationFactory.create()
        prj_1 = ProjectFactory.create(organization=org)
        prj_2 = ProjectFactory.create(organization=org)
        prj_3 = ProjectFactory.create(organization=org)
        prj_4 = ProjectFactory.create(organization=org)

        org_role = OrganizationRole.objects.create(organization=org, user=user)
        ProjectRole.objects.create(project=prj_4, user=user, role='PM')

        data = {
            'org_role': 'M',
            prj_1.id: 'DC',
            prj_2.id: 'PU',
            prj_3.id: 'Pb',
            prj_4.id: 'Pb'
        }

        form = forms.EditOrganizationMemberForm(data, org, user)

        form.save()
        org_role.refresh_from_db()

        assert form.is_valid() is True
        assert org_role.admin is False
        assert ProjectRole.objects.get(user=user, project=prj_1).role == 'DC'
        assert ProjectRole.objects.get(user=user, project=prj_2).role == 'PU'
        assert (ProjectRole.objects.filter(user=user, project=prj_3).exists()
                is False)
        assert (ProjectRole.objects.filter(user=user, project=prj_4).exists()
                is False)


class ProjectEditDetailsTest(TestCase):
    def _get_form(self, form_name):
        path = os.path.dirname(settings.BASE_DIR)
        ensure_dirs()

        storage = FakeS3Storage()
        file = open(
            path + '/questionnaires/tests/files/{}.xlsx'.format(form_name),
            'rb'
        )
        form = storage.save('{}.xlsx'.format(form_name), file)
        return form

    def test_add_new_questionnaire(self):
        project = ProjectFactory.create()
        data = {
            'name': 'New name',
            'questionnaire': self._get_form('xls-form'),
            'access': project.access,
            'contacts-TOTAL_FORMS': 1,
            'contacts-INITIAL_FORMS': 0,
            'contacts-0-name': '',
            'contacts-0-email': '',
            'contacts-0-tel': ''
        }

        form = forms.ProjectEditDetails(instance=project, data=data)
        form.save()

        project.refresh_from_db()
        assert project.name == data['name']
        assert (project.questionnaires.get(
                    id=project.current_questionnaire
                ).xls_form.url == data['questionnaire'])

    def test_add_invalid_questionnaire(self):
        project = ProjectFactory.create()
        data = {
            'name': 'New name',
            'questionnaire': self._get_form('xls-form-invalid'),
            'access': project.access,
            'contacts-TOTAL_FORMS': 1,
            'contacts-INITIAL_FORMS': 0,
            'contacts-0-name': '',
            'contacts-0-email': '',
            'contacts-0-tel': ''
        }

        form = forms.ProjectEditDetails(instance=project, data=data)
        with raises(InvalidXLSForm):
            form.save()

        project.refresh_from_db()
        assert project.name != data['name']
        assert project.current_questionnaire is None

    def test_replace_questionnaire(self):
        project = ProjectFactory.create()
        questionnaire = QuestionnaireFactory.create(
            project=project,
            xls_form=self._get_form('xls-form'))
        data = {
            'name': 'New name',
            'questionnaire': self._get_form('xls-form-copy'),
            'access': project.access,
            'contacts-TOTAL_FORMS': 1,
            'contacts-INITIAL_FORMS': 0,
            'contacts-0-name': '',
            'contacts-0-email': '',
            'contacts-0-tel': ''
        }

        form = forms.ProjectEditDetails(
            instance=project,
            data=data,
            initial={'questionnaire': questionnaire.xls_form.url})
        form.save()

        project.refresh_from_db()
        assert project.name == data['name']
        assert (project.questionnaires.get(
                    id=project.current_questionnaire
                ).xls_form.url == data['questionnaire'])

    def test_delete_questionnaire(self):
        project = ProjectFactory.create()
        questionnaire = QuestionnaireFactory.create(
            project=project,
            xls_form=self._get_form('xls-form'))
        data = {
            'name': 'New name',
            'questionnaire': '',
            'access': project.access,
            'contacts-TOTAL_FORMS': 1,
            'contacts-INITIAL_FORMS': 0,
            'contacts-0-name': '',
            'contacts-0-email': '',
            'contacts-0-tel': ''
        }

        form = forms.ProjectEditDetails(
            instance=project,
            data=data,
            initial={'questionnaire': questionnaire.xls_form.url})
        form.save()

        project.refresh_from_db()
        assert project.name == data['name']
        assert not project.current_questionnaire


class UpdateProjectRolesTest(TestCase):
    def setUp(self):
        self.project = ProjectFactory.create()
        self.user = UserFactory.create()

    def test_create_new_role(self):
        """New ProjectRole instance should be created when role != Pb"""
        forms.create_update_or_delete_project_role(
            self.project.id, self.user, 'PM')

        assert ProjectRole.objects.count() == 1
        assert ProjectRole.objects.first().role == 'PM'

    def test_do_not_create_new_role_for_public_user(self):
        """No ProjectRole instance should be created when role == Pb"""
        forms.create_update_or_delete_project_role(
            self.project.id, self.user, 'Pb')

        assert ProjectRole.objects.count() == 0

    def test_update_existing_role(self):
        ProjectRole.objects.create(
            project=self.project,
            user=self.user,
            role='DC')
        forms.create_update_or_delete_project_role(
            self.project.id, self.user, 'PM')

        role = ProjectRole.objects.get(project=self.project, user=self.user)
        assert role.role == 'PM'

    def test_delete_existing_role(self):
        """If role is updated to Pb (public user) the Project Role instance
           should be deleted"""
        ProjectRole.objects.create(
            project=self.project,
            user=self.user,
            role='DC')
        forms.create_update_or_delete_project_role(
            self.project.id, self.user, 'Pb')
        assert ProjectRole.objects.count() == 0


class ProjectEditPermissionsTest(TestCase):
    def setUp(self):
        self.project = ProjectFactory.create()

        self.super_user = UserFactory.create()
        OrganizationRole.objects.create(user=self.super_user,
                                        organization=self.project.organization,
                                        admin=False)

        PolicyFactory.set_directory(settings.BASE_DIR + '/permissions/')
        su_pol = PolicyFactory.create(name='superuser', file='superuser.json')
        su_role = RoleFactory.create(
            name='superuser',
            policies=[su_pol]
        )
        self.super_user.assign_policies(su_role)

        self.org_admin = UserFactory.create()
        OrganizationRole.objects.create(user=self.org_admin,
                                        organization=self.project.organization,
                                        admin=True)
        self.project_user_1 = UserFactory.create()
        OrganizationRole.objects.create(user=self.project_user_1,
                                        organization=self.project.organization,
                                        admin=False)
        ProjectRole.objects.create(user=self.project_user_1,
                                   project=self.project,
                                   role='DC')
        self.project_user_2 = UserFactory.create()
        OrganizationRole.objects.create(user=self.project_user_2,
                                        organization=self.project.organization,
                                        admin=False)

    def test_init(self):
        form = forms.ProjectEditPermissions(instance=self.project)
        assert len(form.fields) == 4

        for k, field in form.fields.items():
            if field.user == self.project_user_2:
                assert field.initial == 'Pb'
            elif field.user == self.project_user_1:
                assert field.initial == 'DC'
            elif field.user == self.org_admin:
                assert field.initial == 'A'
            elif field.user == self.super_user:
                assert field.initial == 'A'

    def test_save(self):
        data = {
            self.project_user_1.username: 'PM',
            self.project_user_2.username: 'DC'
        }
        form = forms.ProjectEditPermissions(instance=self.project, data=data)
        form.save()

        role_1 = ProjectRole.objects.get(
            project=self.project,
            user=self.project_user_1
        )
        assert role_1.role == 'PM'

        role_2 = ProjectRole.objects.get(
            project=self.project,
            user=self.project_user_2
        )
        assert role_2.role == 'DC'


class ContactsFormTest(TestCase):
    def test_as_table(self):
        form = forms.ContactsForm(prefix='c')
        html = form.as_table()

        expected = (
            '<tr><td><input id="id_c-name" name="c-name" type="text" /></td>\n'
            '<td><input id="id_c-email" name="c-email" type="email" /></td>\n'
            '<td><input id="id_c-tel" name="c-tel" type="text" />'
            '<input id="id_c-remove" name="c-remove" type="hidden" /></td>'
            '<td><a data-prefix="c" '
            'class="close remove-contact" href="#">'
            '<span aria-hidden="true">&times;</span></a></td></tr>'
        )
        assert expected == html

    def test_clean_string(self):
        form = forms.ContactsForm()
        assert form.clean_string('') is None
        assert form.clean_string('somthing') == 'somthing'

    def test_clean_email(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': 'john@beatles.uk'
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        form.full_clean()
        assert form.clean_email() == data['contacts-email']

    def test_clean_email_empty_string(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': '',
            'contacts-tel': '555-555'
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        form.full_clean()
        assert form.clean_email() is None

    def test_clean_tel(self):
        data = {
            'contacts-name': 'John',
            'contacts-tel': '555-5555'
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        form.full_clean()
        assert form.clean_tel() == data['contacts-tel']

    def test_clean_tel_empty_string(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': 'john@beatles.uk',
            'contacts-tel': ''
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        form.full_clean()
        assert form.clean_tel() is None

    def test_full_clean(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': 'john@beatles.uk'
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        form.full_clean()
        assert form.cleaned_data == {
            'name': 'John',
            'email': 'john@beatles.uk',
            'tel': None,
            'remove': False
        }

    def test_full_clean_remove(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': 'john@beatles.uk',
            'contacts-remove': 'on'
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        form.full_clean()
        assert form.cleaned_data == {'remove': True}

    def test_validate_valid_form_with_email(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': 'john@beatles.uk',
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        assert form.is_valid() is True

    def test_validate_valid_form_with_tel(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': '',
            'contacts-tel': '555-555'
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        assert form.is_valid() is True

    def test_validate_invalid_form(self):
        data = {
            'contacts-name': 'John',
            'contacts-email': '',
            'contacts-tel': ''
        }
        form = forms.ContactsForm(data=data, prefix='contacts')
        assert form.is_valid() is False
        assert ("Please provide either email or phone number" in
                form.errors['__all__'])
