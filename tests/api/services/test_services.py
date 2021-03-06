# coding= utf-8

# Copyright (c) 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import cgi
import time
import urlparse
import uuid

import ddt
import jsonpatch
from nose.plugins import attrib

from tests.api import base
from tests.api import providers
from tests.api.utils.schema import services


@ddt.ddt
class TestCreateService(providers.TestProviderBase):

    """Tests for Create Service."""

    def setUp(self):
        super(TestCreateService, self).setUp()
        self.service_url = ''
        self.service_name = self.generate_random_string(
            prefix='api-test-service')
        self.flavor_id = self.test_flavor

    @ddt.file_data('data_create_service.json')
    def test_create_service_positive(self, test_data):

        domain_list = test_data['domain_list']
        for item in domain_list:
            item['domain'] = self.generate_random_string(
                prefix='api-test-domain') + '.com'
        origin_list = test_data['origin_list']
        caching_list = test_data['caching_list']
        log_delivery = test_data.get('log_delivery')
        flavor_id = self.flavor_id

        resp = self.client.create_service(service_name=self.service_name,
                                          domain_list=domain_list,
                                          origin_list=origin_list,
                                          caching_list=caching_list,
                                          flavor_id=flavor_id,
                                          log_delivery=log_delivery)

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.text, '')
        self.service_url = resp.headers['location']

        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        resp = self.client.get_service(location=self.service_url)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertSchema(body, services.get_service)

        for item in domain_list:
            if 'protocol' not in item:
                item['protocol'] = 'http'
        self.assertEqual(body['domains'], domain_list)

        for item in origin_list:
            if 'rules' not in item:
                item[u'rules'] = []
        self.assertEqual(body['origins'], origin_list)

        # TODO(malini): uncomment below after caching list is implemented.
        # self.assertEqual(body['caching_list'], caching_list)

        # Verify the service is updated at all Providers for the flavor
        if self.test_config.provider_validation:
            service_details = (
                self.getServiceFromFlavor(flavor_id, self.service_name))
            provider_list = self.config.flavor[flavor_id]

            # Verify that the service stored in each provider (that is part of
            # the flavor) is what Poppy sent them.
            for provider in provider_list:
                self.assertEqual(
                    sorted(service_details[provider]['domain_list']),
                    sorted(domain_list),
                    msg='Domain Lists Not Correct for {0} service name {1}'.
                        format(provider, self.service_name))
                self.assertEqual(
                    sorted(service_details[provider]['origin_list']),
                    sorted(origin_list),
                    msg='Origin List Not Correct for {0} service name {1}'.
                        format(provider, self.service_name))
                self.assertEqual(
                    sorted(service_details[provider]['caching_list']),
                    sorted(caching_list),
                    msg='Caching List Not Correct for {0} service name {1}'.
                        format(provider, self.service_name))

    @ddt.file_data('data_create_service_negative.json')
    def test_create_service_negative(self, test_data):

        service_name = test_data['service_name']
        domain_list = test_data['domain_list']
        for item in domain_list:
            if len(item['domain']) > 2:
                item['domain'] = str(uuid.uuid1()) + item['domain']

        origin_list = test_data['origin_list']
        caching_list = test_data['caching_list']
        restrictions_list = test_data['restrictions_list']
        if 'flavor_id' in test_data:
            flavor_id = test_data['flavor_id']
        else:
            flavor_id = self.flavor_id

        resp = self.client.create_service(service_name=service_name,
                                          domain_list=domain_list,
                                          origin_list=origin_list,
                                          caching_list=caching_list,
                                          restrictions_list=restrictions_list,
                                          flavor_id=flavor_id)
        if 'location' in resp.headers:
            self.service_url = resp.headers['location']

        self.assertEqual(resp.status_code, 400)

    @ddt.file_data("data_create_service_xss.json")
    def test_create_service_with_xss_injection(self, test_data):
        # create with hacker data
        service_name = test_data['name']
        domain_list = test_data['domain_list']
        for item in domain_list:
            item['domain'] = self.generate_random_string(
                prefix='api-test-xss') + '.com'

        origin_list = test_data['origin_list']
        caching_list = test_data['caching_list']

        if 'flavor_id' in test_data:
            flavor_id = test_data['flavor_id']
        else:
            flavor_id = self.flavor_id

        resp = self.client.create_service(service_name=service_name,
                                          domain_list=domain_list,
                                          origin_list=origin_list,
                                          caching_list=caching_list,
                                          flavor_id=flavor_id)
        if 'location' in resp.headers:
            self.service_url = resp.headers['location']

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.text, '')
        self.service_url = resp.headers['location']

        resp = self.client.get_service(location=self.service_url)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()

        # validate name
        self.assertEqual(
            body['name'],
            cgi.escape(test_data['name'])
        )

        # validate domain
        self.assertEqual(
            body['domains'][0]['domain'],
            cgi.escape(domain_list[0]['domain'])
        )

        # validate origin
        self.assertEqual(
            body['origins'][0]['origin'],
            cgi.escape(origin_list[0]['origin'])
        )

        if len(caching_list) > 0:
            # validate caching name
            self.assertEqual(
                body['caching'][1]['name'],
                cgi.escape(caching_list[1]['name'])
            )

            if len(caching_list) > 1:
                # we have more than just the default
                if len(caching_list[1]['rules']) > 0:
                    # validate caching rule name
                    self.assertEqual(
                        body['caching'][1]['rules'][0]['name'],
                        cgi.escape(caching_list[1]['rules'][0]['name'])
                    )

                    # validate caching rule request_url
                    self.assertEqual(
                        body['caching'][1]['rules'][0]['request_url'],
                        cgi.escape(caching_list[1]['rules'][0]['request_url'])
                    )

    def tearDown(self):
        if self.service_url != '':
            self.client.delete_service(location=self.service_url)

        if self.test_config.generate_flavors:
            self.client.delete_flavor(flavor_id=self.flavor_id)

        super(TestCreateService, self).tearDown()


@ddt.ddt
class TestListServices(base.TestBase):

    """Tests for List Services."""

    def _create_test_service(self):
        service_name = str(uuid.uuid1())

        self.domain_list = [{"domain": self.generate_random_string(
            prefix='api-test-domain') + '.com'}]

        self.origin_list = [{"origin": self.generate_random_string(
            prefix='api-test-origin') + '.com', "port": 80, "ssl": False}]

        self.caching_list = [{"name": "default", "ttl": 3600},
                             {"name": "home", "ttl": 1200,
                              "rules": [{"name": "index",
                                         "request_url": "/index.htm"}]}]
        self.log_delivery = {"enabled": False}

        resp = self.client.create_service(service_name=service_name,
                                          domain_list=self.domain_list,
                                          origin_list=self.origin_list,
                                          caching_list=self.caching_list,
                                          flavor_id=self.flavor_id,
                                          log_delivery=self.log_delivery)

        self.service_url = resp.headers["location"]
        return self.service_url

    def setUp(self):
        super(TestListServices, self).setUp()
        self.service_list = []
        self.flavor_id = self.test_flavor

    def test_list_single_service(self):
        self.service_list.append(self._create_test_service())
        resp = self.client.list_services()
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertSchema(body, services.list_services)

    def test_list_services_no_service(self):
        self.skipTest('Non deterministic - Replace this with an unit test?')
        resp = self.client.list_services()
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body['services'], [])
        self.assertEqual(body['links'], [])

    @ddt.data(1, 5, 10)
    def test_list_services_valid_limit(self, limit):
        self.service_list = [self._create_test_service() for _ in range(limit)]
        url_param = {'limit': limit}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(len(body['services']), limit)
        self.assertSchema(body, services.list_services)

    @ddt.data(3)
    def test_list_services_multiple_page(self, num):
        self.service_list = [self._create_test_service() for _ in range(num)]
        url_param = {'limit': num - 1}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(len(body['services']), num - 1)
        self.assertSchema(body, services.list_services)

        # get second page
        next_page_uri = urlparse.urlparse(body['links'][0]['href'])
        marker = urlparse.parse_qs(next_page_uri.query)['marker'][0]
        url_param = {'marker': marker, 'limit': 1}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(len(body['services']), 1)
        self.assertSchema(body, services.list_services)

    @ddt.data(-1, -10000000000, 0, 10000000, 'invalid', '')
    def test_list_services_invalid_limits(self, limit):
        url_param = {'limit': limit}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 400)

    @ddt.data(-1, -10000000000, 0, 10000000, 'invalid', '学校', '')
    def test_list_services_various_invalid_markers(self, marker):
        url_param = {'marker': marker}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 400)

    def test_list_services_markers(self):
        url_param = {'marker': str(uuid.uuid4())}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 200)

    def test_list_services_invalid_param(self):
        url_param = {'yummy': 123}
        resp = self.client.list_services(param=url_param)
        self.assertEqual(resp.status_code, 200)

    def tearDown(self):
        for service in self.service_list:
            self.client.delete_service(location=service)

        if self.test_config.generate_flavors:
            self.client.delete_flavor(flavor_id=self.flavor_id)

        super(TestListServices, self).tearDown()


@ddt.ddt
class TestServiceActions(base.TestBase):

    def setUp(self):
        super(TestServiceActions, self).setUp()
        self.service_name = self.generate_random_string(prefix='API-Test-')
        self.flavor_id = self.test_flavor

        domain = self.generate_random_string(
            prefix='api-test-domain') + u'.com'
        self.domain_list = [
            {"domain": domain, "protocol": "http"}
        ]

        origin = self.generate_random_string(
            prefix='api-test-origin') + u'.com'
        self.origin_list = [
            {
                u"origin": origin,
                u"port": 80,
                u"ssl": False,
                u"rules": [{
                    u"name": u"default",
                    u"request_url": u"/*"
                }]
            }
        ]

        self.caching_list = [
            {
                u"name": u"default",
                u"ttl": 3600,
                u"rules": [{
                    u"name": "default",
                    u"request_url": "/*"
                }]
            },
            {
                u"name": u"home",
                u"ttl": 1200,
                u"rules": [{
                    u"name": u"index",
                    u"request_url": u"/index.htm"
                }]
            }
        ]

        self.restrictions_list = [
            {
                u"name": u"website only",
                u"rules": [
                    {
                        u"name": domain,
                        u"referrer": domain,
                        u"request_url": "/*"
                    }
                ]
            }
        ]

        resp = self.client.create_service(
            service_name=self.service_name,
            domain_list=self.domain_list,
            origin_list=self.origin_list,
            caching_list=self.caching_list,
            restrictions_list=self.restrictions_list,
            flavor_id=self.flavor_id)

        self.service_url = resp.headers["location"]
        self.client.wait_for_service_status(
            location=self.service_url, status='deployed')

    @attrib.attr('smoke')
    def test_delete_service(self):
        resp = self.client.delete_service(location=self.service_url)
        self.assertEqual(resp.status_code, 202)

        start_time = int(time.time())
        stop_time = start_time + self.test_config.status_check_retry_timeout
        current_status = 0
        expected_status = 404
        while (current_status != expected_status):
            service_deleted = self.client.get_service(
                location=self.service_url)
            current_status = service_deleted.status_code
            current_time = int(time.time())
            if current_time > stop_time:
                break

        self.assertEqual(404, current_status)

    def test_delete_non_existing_service(self):
        url = self.service_url.rsplit('/', 1)[0] + str(uuid.uuid4())
        resp = self.client.delete_service(location=url)
        self.assertEqual(resp.status_code, 404)

    def test_delete_failed_service(self):
        # TODO(malini): Add test to verify that a failed service can be
        # deleted.
        # Placeholder till we figure out how to create provider side failure.
        self.skipTest(
            'Until we figure out how to create provider side failure.')

    def test_delete_service_race_condition(self):
        resp1 = self.client.delete_service(location=self.service_url)
        resp2 = self.client.delete_service(location=self.service_url)
        self.assertEqual(resp1.status_code, 202)
        self.assertEqual(resp2.status_code, 202)

        time.sleep(10)
        exception = False
        try:
            self.client.get_service(location=self.service_url)
        except Exception:
            exception = True

        self.assertFalse(exception)

    @attrib.attr('smoke')
    def test_get_service(self):
        resp = self.client.get_service(location=self.service_url)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertSchema(body, services.get_service)

        for item in self.domain_list:
            if 'protocol' not in item:
                item['protocol'] = 'http'
        self.assertEqual(body['domains'], self.domain_list)

        self.assertEqual(body['origins'], self.origin_list)
        self.assertEqual(body['caching'], self.caching_list)
        self.assertEqual(body['restrictions'], self.restrictions_list)
        self.assertEqual(body['flavor_id'], self.flavor_id)

    def test_get_non_existing_service(self):
        url = self.service_url.rsplit('/', 1)[0] + str(uuid.uuid4())
        resp = self.client.get_service(location=url)
        self.assertEqual(resp.status_code, 404)

    def test_get_failed_service(self):
        # TODO(malini): Add test to verify that failed service will return
        # status 'failed' on get_service with error message from the provider.
        # Placeholder till we figure out how to create provider side failure.
        self.skipTest(
            'Until we figure out how to create provider side failure.')

    def tearDown(self):
        self.client.delete_service(location=self.service_url)
        if self.test_config.generate_flavors:
            self.client.delete_flavor(flavor_id=self.flavor_id)
        super(TestServiceActions, self).tearDown()


@ddt.ddt
class TestServicePatch(base.TestBase):

    """Tests for PATCH Services."""

    def setUp(self):
        super(TestServicePatch, self).setUp()
        self.service_name = self.generate_random_string(prefix='api-test')
        self.flavor_id = self.test_flavor
        self.log_delivery = {"enabled": False}

        domain = self.generate_random_string(prefix='api-test-domain') + '.com'
        self.domain_list = [
            {
                "domain": domain,
                "protocol": "http"
            }
        ]

        origin = self.generate_random_string(prefix='api-test-origin') + '.com'
        self.origin_list = [
            {
                "origin": origin,
                "port": 80,
                "ssl": False,
                "rules": [
                    {
                        "name": "default",
                        "request_url": "/*"
                    }
                ]
            }
        ]

        self.caching_list = [
            {
                "name": "default",
                "ttl": 3600,
                "rules": [
                    {
                        "name": "default",
                        "request_url": "/*"
                    }
                ]
            },
            {
                "name": "home",
                "ttl": 1200,
                "rules": [
                    {
                        "name": "index",
                        "request_url": "/index.htm"
                    }
                ]
            }
        ]

        self.restrictions_list = [
            {"name": "website only",
             "rules": [{"name": "mywebsite.com",
                        "referrer": "www.mywebsite.com",
                        "request_url": "/*"
                        }]}]

        resp = self.client.create_service(
            service_name=self.service_name,
            domain_list=self.domain_list,
            origin_list=self.origin_list,
            caching_list=self.caching_list,
            restrictions_list=self.restrictions_list,
            flavor_id=self.flavor_id,
            log_delivery=self.log_delivery)

        self.service_url = resp.headers["location"]

        self.original_service_details = {
            "name": self.service_name,
            "domains": self.domain_list,
            "origins": self.origin_list,
            "caching": self.caching_list,
            "restrictions": self.restrictions_list,
            "flavor_id": self.flavor_id,
            "log_delivery": self.log_delivery}

        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        resp = self.client.get_service(location=self.service_url)
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body['status'], 'deployed')

    def _replace_domain(self, domain):
        if ('protocol' in domain):
            if domain['protocol'] == 'https':
                if (domain['certificate'] == u'shared'):
                    return self.generate_random_string(prefix='api-test-ssl')

        return self.generate_random_string(prefix='api-test-ssl') + '.com'

    @ddt.file_data('data_patch_service.json')
    def test_patch_service(self, test_data):

        for item in test_data:
            if 'skip_test' in item:
                self.skipTest('Not Implemented - bug# 1433807')

            if ('domain' in item['path']) and ('value' in item):
                if isinstance(item['value'], (list)):
                    item['value'][0]['domain'] = self._replace_domain(
                        domain=item['value'][0])
                else:
                    item['value']['domain'] = self._replace_domain(
                        domain=item['value'])

        patch = jsonpatch.JsonPatch(test_data)
        expected_service_details = patch.apply(self.original_service_details)

        resp = self.client.patch_service(location=self.service_url,
                                         request_body=test_data)
        self.assertEqual(resp.status_code, 202)

        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        resp = self.client.get_service(location=self.service_url)
        body = resp.json()
        self.assertEqual(body['status'], 'deployed')

        self.assert_patch_service_details(body, expected_service_details)

    @ddt.file_data('data_patch_service_negative.json')
    def test_patch_service_HTTP_400(self, test_data):

        resp = self.client.patch_service(location=self.service_url,
                                         request_body=test_data)
        self.assertEqual(resp.status_code, 400)

        # nothing should have changed.
        resp = self.client.get_service(location=self.service_url)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertEqual(body['status'], 'deployed')

        self.assert_patch_service_details(body, self.original_service_details)

    def test_patch_service_claim_relinquish_domain(self):
        newdomain = str(uuid.uuid4()) + ".com"
        add_domain = (
            [{
                "op": "add",
                "path": "/domains/-",
                "value": {"domain": newdomain, "protocol": "http"}
            }])
        remove_domain = (
            [{
                "op": "remove",
                "path": "/domains/1"
            }])

        # add new domain
        resp = self.client.patch_service(location=self.service_url,
                                         request_body=add_domain)
        self.assertEqual(resp.status_code, 202)

        # wait for the domain to be added
        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        # make sure the new domain is added
        resp = self.client.get_service(location=self.service_url)
        body = resp.json()
        self.assertEqual(body['status'], 'deployed')
        self.assertEqual(body['domains'][-1]['domain'], newdomain)

        # remove the new domain
        resp = self.client.patch_service(location=self.service_url,
                                         request_body=remove_domain)
        self.assertEqual(resp.status_code, 202)

        # wait for the domain to be removed
        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)
        # make sure the new domain is removed
        resp = self.client.get_service(location=self.service_url)
        body = resp.json()
        self.assertEqual(body['status'], 'deployed')
        for domain in body['domains']:
            self.assertNotEqual(domain['domain'], newdomain)

        # add new domain, again
        resp = self.client.patch_service(location=self.service_url,
                                         request_body=add_domain)
        self.assertEqual(resp.status_code, 202)

        # wait for the domain to be added
        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        # make sure the new domain is added
        resp = self.client.get_service(location=self.service_url)
        body = resp.json()
        self.assertEqual(body['status'], 'deployed')
        self.assertEqual(body['domains'][-1]['domain'], newdomain)

    def test_patch_service_add_duplicate_domain(self):
        # create second service
        service_name = str(uuid.uuid1())
        duplicate_domain = str(uuid.uuid1()) + '.com'
        domain_list = [{"domain": duplicate_domain, "protocol": "http"}]

        origin = str(uuid.uuid1()) + '.com'
        origin_list = [{"origin": origin,
                        "port": 80, "ssl": False, "rules": []}]

        resp = self.client.create_service(
            service_name=service_name,
            domain_list=domain_list,
            origin_list=origin_list,
            flavor_id=self.flavor_id)

        service_url = resp.headers["location"]

        # wait until the service is deployed
        self.client.wait_for_service_status(
            location=service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        resp = self.client.get_service(location=service_url)
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body['status'], 'deployed')

        # wait to make sure cassandra is eventually consistent
        time.sleep(self.test_config.cassandra_consistency_wait_time)

        # patch original service with the duplicate domain
        add_duplicate_domain = (
            [{
                "op": "add",
                "path": "/domains/-",
                "value": {"domain": duplicate_domain, "protocol": "http"}
            }])

        # add the duplicate domain
        resp = self.client.patch_service(location=self.service_url,
                                         request_body=add_duplicate_domain)
        self.assertEqual(resp.status_code, 400)

    def tearDown(self):
        self.client.delete_service(location=self.service_url)
        if self.test_config.generate_flavors:
            self.client.delete_flavor(flavor_id=self.flavor_id)
        super(TestServicePatch, self).tearDown()


@ddt.ddt
class TestDefaultServiceFields(providers.TestProviderBase):

    """Tests for Default Service Fields."""

    def setUp(self):
        super(TestDefaultServiceFields, self).setUp()
        self.service_url = ''
        self.service_name = self.generate_random_string(prefix='api-test')
        self.flavor_id = self.test_flavor

    @ddt.file_data('data_default_service_values.json')
    def test_default_values(self, test_data):

        domain_list = test_data['submit_value'].get('domain_list', [])
        for item in domain_list:
            item['domain'] = str(uuid.uuid1()) + '.com'

        origin_list = test_data['submit_value'].get('origin_list', [])
        caching_list = test_data['submit_value'].get('caching_list', [])
        restrictions_list = test_data['submit_value'].get('restrictions', [])
        flavor_id = self.flavor_id

        resp = self.client.create_service(service_name=self.service_name,
                                          domain_list=domain_list,
                                          origin_list=origin_list,
                                          caching_list=caching_list,
                                          restrictions_list=restrictions_list,
                                          flavor_id=flavor_id)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.text, '')
        self.service_url = resp.headers['location']

        self.client.wait_for_service_status(
            location=self.service_url,
            status='deployed',
            abort_on_status='failed',
            retry_interval=self.test_config.status_check_retry_interval,
            retry_timeout=self.test_config.status_check_retry_timeout)

        resp = self.client.get_service(location=self.service_url)
        self.assertEqual(resp.status_code, 200)

        body = resp.json()
        self.assertSchema(body, services.get_service)

        expected_domain_list = domain_list
        expected_origin_list = test_data[
            'expected_value'].get('origin_list', [])
        expected_caching_list = test_data[
            'expected_value'].get('caching_list', [])
        expected_restrictions_list = test_data[
            'expected_value'].get('restrictions', [])

        self.assertEqual(body['domains'], expected_domain_list)
        self.assertEqual(body['origins'], expected_origin_list)
        self.assertEqual(body['caching'], expected_caching_list)
        self.assertEqual(body['restrictions'], expected_restrictions_list)

    def tearDown(self):
        if self.service_url != '':
            self.client.delete_service(location=self.service_url)

        if self.test_config.generate_flavors:
            self.client.delete_flavor(flavor_id=self.flavor_id)

        super(TestDefaultServiceFields, self).tearDown()
