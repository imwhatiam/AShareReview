import json

from django.core.cache import cache
from django.test import TestCase


class LoginThrottleTests(TestCase):
    """登录失败预算：按 (客户端地址, 用户名) 计数，成功即清零。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _post_login(self, client, username, password):
        return client.post(
            '/api/core/login/',
            data=json.dumps({'username': username, 'password': password}),
            content_type='application/json',
        )

    def test_repeated_failures_are_throttled_and_a_success_resets_the_budget(self):
        from django.contrib.auth import get_user_model

        from core.services import login_throttle

        user = get_user_model().objects.create_user(
            username='throttled', password='correct-password'
        )
        client = self.client

        for attempt in range(login_throttle.MAX_FAILURES_DEFAULT):
            response = self._post_login(client, user.username, 'wrong-password')
            self.assertEqual(response.status_code, 401, f'attempt {attempt}')
            self.assertEqual(
                login_throttle.failure_count(user.username, '127.0.0.1'), attempt + 1
            )

        locked = self._post_login(client, user.username, 'correct-password')
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(locked.json()['error']['code'], 'TOO_MANY_ATTEMPTS')

        # 正确的密码也解不开锁：预算必须真的能挡住爆破。
        self.assertFalse(client.get('/api/core/session/').json()['data']['authenticated'])

        # 换一个客户端地址不受影响（键是地址 + 用户名，不是全局计数）。
        self.assertFalse(login_throttle.is_locked(user.username, '10.0.0.9'))

    def test_a_successful_login_clears_the_counter(self):
        from django.contrib.auth import get_user_model

        from core.services import login_throttle

        user = get_user_model().objects.create_user(
            username='reset-me', password='correct-password'
        )

        self._post_login(self.client, user.username, 'wrong-password')
        self.assertEqual(login_throttle.failure_count(user.username, '127.0.0.1'), 1)

        response = self._post_login(self.client, user.username, 'correct-password')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(login_throttle.failure_count(user.username, '127.0.0.1'), 0)

    def test_a_malformed_body_does_not_spend_a_budget(self):
        from core.services import login_throttle

        response = self.client.post(
            '/api/core/login/', data='not-json', content_type='application/json'
        )

        self.assertEqual(response.status_code, 401)
        # 没有用户名就没有可计数的键，也不该把「空用户名」锁死。
        self.assertFalse(login_throttle.is_locked('', '127.0.0.1'))
