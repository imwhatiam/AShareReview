import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class SessionApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='regular-user',
            password='correct-password',
        )
        self.staff_user = user_model.objects.create_user(
            username='staff-user',
            password='correct-password',
            is_staff=True,
        )

    def test_session_returns_anonymous_state_and_csrf_token(self):
        response = self.client.get('/api/core/session/')
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertIsNone(body['business_date'])
        self.assertIsNone(body['data_version'])
        self.assertFalse(body['stale'])
        self.assertEqual(body['source'], 'application')
        self.assertFalse(body['data']['authenticated'])
        self.assertIsNone(body['data']['user'])
        self.assertTrue(body['data']['csrf_token'])
        self.assertIn('csrftoken', response.cookies)

    def test_valid_login_creates_a_session_and_returns_user_summary(self):
        client = Client(enforce_csrf_checks=True)
        csrf_token = self._get_csrf_token(client)

        login_response = client.post(
            '/api/core/login/',
            data=json.dumps({
                'username': self.user.username,
                'password': 'correct-password',
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        login_body = json.loads(login_response.content)
        session_response = client.get('/api/core/session/')
        session_body = json.loads(session_response.content)

        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_body['data']['authenticated'])
        self.assertEqual(login_body['data']['user']['username'], 'regular-user')
        self.assertFalse(login_body['data']['user']['is_staff'])
        self.assertEqual(session_response.status_code, 200)
        self.assertTrue(session_body['data']['authenticated'])
        self.assertEqual(session_body['data']['user']['username'], 'regular-user')

    def test_invalid_login_uses_the_same_error_for_unknown_user_and_bad_password(self):
        client = Client(enforce_csrf_checks=True)
        csrf_token = self._get_csrf_token(client)

        unknown_response = client.post(
            '/api/core/login/',
            data=json.dumps({'username': 'unknown-user', 'password': 'wrong'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        bad_password_response = client.post(
            '/api/core/login/',
            data=json.dumps({
                'username': self.user.username,
                'password': 'wrong',
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        unknown_body = json.loads(unknown_response.content)
        bad_password_body = json.loads(bad_password_response.content)

        self.assertEqual(unknown_response.status_code, 401)
        self.assertEqual(bad_password_response.status_code, 401)
        self.assertEqual(unknown_body['error'], bad_password_body['error'])
        self.assertEqual(unknown_body['error']['code'], 'AUTH_REQUIRED')

    def test_login_and_logout_reject_requests_without_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        self._get_csrf_token(client)

        login_response = client.post(
            '/api/core/login/',
            data=json.dumps({
                'username': self.user.username,
                'password': 'correct-password',
            }),
            content_type='application/json',
        )
        login_body = json.loads(login_response.content)

        self.assertEqual(login_response.status_code, 403)
        # CSRF 失败有自己的错误码：`INVALID_PARAMETER` 会让调用方去查参数，
        # 而这里的正确动作是刷新页面/重新登录。
        self.assertEqual(login_body['error']['code'], 'CSRF_FAILED')

        csrf_token = self._get_csrf_token(client)
        client.post(
            '/api/core/login/',
            data=json.dumps({
                'username': self.user.username,
                'password': 'correct-password',
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        logout_response = client.post('/api/core/logout/')
        logout_body = json.loads(logout_response.content)

        self.assertEqual(logout_response.status_code, 403)
        self.assertEqual(logout_body['error']['code'], 'CSRF_FAILED')
        self.assertTrue(client.get('/api/core/session/').json()['data']['authenticated'])

    def test_logout_clears_the_session(self):
        client = Client(enforce_csrf_checks=True)
        csrf_token = self._get_csrf_token(client)
        client.post(
            '/api/core/login/',
            data=json.dumps({
                'username': self.user.username,
                'password': 'correct-password',
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        refreshed_csrf_token = self._get_csrf_token(client)
        logout_response = client.post(
            '/api/core/logout/',
            HTTP_X_CSRFTOKEN=refreshed_csrf_token,
        )
        logout_body = json.loads(logout_response.content)
        session_body = client.get('/api/core/session/').json()

        self.assertEqual(logout_response.status_code, 200)
        self.assertFalse(logout_body['data']['authenticated'])
        self.assertFalse(session_body['data']['authenticated'])

    def test_staff_session_summary_identifies_staff_status(self):
        self.client.force_login(self.staff_user)

        response = self.client.get('/api/core/session/')
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body['data']['authenticated'])
        self.assertTrue(body['data']['user']['is_staff'])

    def _get_csrf_token(self, client):
        response = client.get('/api/core/session/')
        return response.json()['data']['csrf_token']
