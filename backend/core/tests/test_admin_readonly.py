from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminReadOnlyTests(TestCase):
    """后台只读：运维可以查库里的数据，但不能在页面上改。

    这条契约以前挂在运行状态表上；那张表删掉之后，仍然留在后台的是公共参考数据
    与派生结果，而它们都只能由管理命令写 —— 后台改出来的行绕过了命令的覆盖度校验
    与整批事务，是最容易把"某一天完整不完整"搞乱的地方。
    """

    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username='admin-user',
            password='password',
            is_staff=True,
        )
        self.user = user_model.objects.create_user(
            username='regular-user',
            password='password',
        )

    def test_staff_can_read_the_remaining_data_pages(self):
        self.client.force_login(self.staff_user)

        for model_name in ('stock', 'industry', 'dailyprice'):
            with self.subTest(model=model_name):
                if model_name == 'stock':
                    url = reverse('admin:core_stock_changelist')
                elif model_name == 'industry':
                    url = reverse('admin:core_industrysnapshot_changelist')
                else:
                    url = reverse('admin:core_dailyprice_changelist')
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_non_staff_user_cannot_access_the_admin(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('admin:core_stock_changelist'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])

    def test_every_registered_page_refuses_to_add(self):
        self.client.force_login(self.staff_user)

        for model_name in ('stock', 'industry', 'dailyprice'):
            with self.subTest(model=model_name):
                if model_name == 'stock':
                    url = reverse('admin:core_stock_add')
                elif model_name == 'industry':
                    url = reverse('admin:core_industrysnapshot_add')
                else:
                    url = reverse('admin:core_dailyprice_add')
                self.assertEqual(self.client.get(url).status_code, 403)
