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

import random
try:
    set
except NameError:  # noqa  pragma: no cover
    from sets import Set as set  # noqa  pragma: no cover

import pyrax.exceptions as exc

from poppy.dns import base
from poppy.openstack.common import log

LOG = log.getLogger(__name__)


class ServicesController(base.ServicesBase):

    def __init__(self, driver):
        super(ServicesController, self).__init__(driver)

        self.client = driver.client

    def _get_subdomain(self, subdomain_name):
        """Returns a subdomain, if it does not exist, create it

        :param subdomain_name
        :return subdomain
        """

        try:
            subdomain = self.client.find(name=subdomain_name)
        except exc.NotFound:
            subdomain = self.client.create(
                name=subdomain_name,
                emailAddress=self._driver.rackdns_conf.email,
                ttl=900)
        return subdomain

    def _create_cname_records(self, links):
        """Creates a subdomain

        :param links: Access URLS from providers
        :return dns_links: Map from provider access URL to DNS access URL
        """

        cdn_domain_name = self._driver.rackdns_conf.url
        shard_prefix = self._driver.rackdns_conf.shard_prefix
        num_shards = self._driver.rackdns_conf.num_shards

        # randomly select a shard
        shard_id = random.randint(1, num_shards)
        subdomain_name = '{0}{1}.{2}'.format(shard_prefix, shard_id,
                                             cdn_domain_name)
        subdomain = self._get_subdomain(subdomain_name)
        # create CNAME record for adding
        cname_records = []

        dns_links = {}

        shared_ssl_subdomain_name = None
        for link in links:
            # pick out shared ssl domains here
            domain_name, certificate = link
            if certificate == "shared":
                shared_ssl_subdomain_name = (
                    '.'.join(domain_name.split('.')[1:]))
                # perform shared ssl cert logic
                name = domain_name
            else:
                name = '{0}.{1}'.format(domain_name, subdomain_name)

            cname_record = {'type': 'CNAME',
                            'name': name,
                            'data': links[link],
                            'ttl': 300}
            dns_links[link] = {
                'provider_url': links[link],
                'operator_url': name
            }

            if certificate == "shared":
                shared_ssl_subdomain = self._get_subdomain(
                    shared_ssl_subdomain_name)
                shared_ssl_subdomain.add_records([cname_record])
            else:
                cname_records.append(cname_record)
        # add the cname records
        if cname_records != []:
            subdomain.add_records(cname_records)
        return dns_links

    def _delete_cname_record(self, access_url, shared_ssl_flag):
        """Delete a CNAME record

        :param access_url: DNS Access URL
        :return error_msg: returns error message, if any
        """

        # extract shard name
        if shared_ssl_flag:
            suffix = self._driver.rackdns_conf.shared_ssl_domain_suffix
        else:
            suffix = self._driver.rackdns_conf.url
        # Note: use rindex to find last occurence of the suffix
        shard_name = access_url[:access_url.rindex(suffix)-1].split('.')[-1]
        subdomain_name = '.'.join([shard_name, suffix])

        # for sharding is disabled, the suffix is the subdomain_name
        if shared_ssl_flag and (
                self._driver.rackdns_conf.shared_ssl_num_shards == 0):
            subdomain_name = suffix
        # get subdomain
        subdomain = self.client.find(name=subdomain_name)
        # search and find the CNAME record
        name = access_url
        record_type = 'CNAME'
        records = self.client.search_records(subdomain, record_type, name)
        # delete the record
        # we should get one record,
        # or none if it has been deleted already
        if not records:
            LOG.info('DNS record already deleted: {0}'.format(access_url))
        elif len(records) == 1:
            LOG.info('Deleting DNS records for : {0}'.format(access_url))
            records[0].delete()
        elif len(records) > 1:
            error_msg = 'Multiple DNS records found: {0}'.format(access_url)
            return error_msg
        return

    def _generate_sharded_domain_name(self, shard_prefix, num_shards, suffix):
        """Generate a sharded domain name based on the scheme:

        '{shard_prefix}{a random shard_id}.{suffix}'

        :return A string of sharded domain name
        """
        if num_shards == 0:
            # shard disabled, just use the suffix
            return suffix
        else:
            # shard enabled, randomly select a shard
            shard_id = random.randint(1, num_shards)
            return '{0}{1}.{2}'.format(shard_prefix, shard_id, suffix)

    def generate_shared_ssl_domain_suffix(self):
        """Rackespace DNS scheme to generate a shared ssl domain suffix,

        to be used with manager for shared ssl feature

        :return A string of shared ssl domain name
        """
        return self._generate_sharded_domain_name(
            self._driver.rackdns_conf.shared_ssl_shard_prefix,
            self._driver.rackdns_conf.shared_ssl_num_shards,
            self._driver.rackdns_conf.shared_ssl_domain_suffix)

    def create(self, responders):
        """Create CNAME record for a service.

        :param responders: responders from providers
        :return dns_links: Map from provider urls to DNS urls
        """

        providers = []
        for responder in responders:
            for provider in responder:
                providers.append(provider)

        for responder in responders:
            for provider_name in responder:
                if 'error' in responder[provider_name]:
                    error_msg = responder[provider_name]['error_detail']
                    return self.responder.failed(providers, error_msg)

        # gather the provider urls and cname them
        links = {}
        for responder in responders:
            for provider_name in responder:
                for link in responder[provider_name]['links']:
                    if link['rel'] == 'access_url':
                        # We need to distinguish shared ssl domains in
                        # which case the we will use different shard prefix and
                        # and shard number
                        links[(link['domain'], link.get('certificate',
                                                        None))] = link['href']

        # create CNAME records
        try:
            dns_links = self._create_cname_records(links)
        except Exception as e:
            error_msg = 'Rackspace DNS Exception: {0}'.format(e)
            LOG.error(error_msg)
            return self.responder.failed(providers, error_msg)

        # gather the CNAMED links
        dns_details = {}
        for responder in responders:
            for provider_name in responder:
                access_urls = []
                for link in responder[provider_name]['links']:
                    if link['rel'] == 'access_url':
                        access_url = {
                            'domain': link['domain'],
                            'provider_url':
                                dns_links[(link['domain'],
                                           link.get('certificate', None)
                                           )]['provider_url'],
                            'operator_url':
                                dns_links[(link['domain'],
                                           link.get('certificate', None)
                                           )]['operator_url']}
                        # Need to indicate if this access_url is a shared ssl
                        # access url, since its has different shard_prefix and
                        # num_shard
                        if link.get('certificate', None) == 'shared':
                            access_url['shared_ssl_flag'] = True

                        access_urls.append(access_url)
                dns_details[provider_name] = {'access_urls': access_urls}
        return self.responder.created(dns_details)

    def delete(self, provider_details):
        """Delete CNAME records for a service.

        :param provider_details
        :return dns_details: Map from provider_name to delete errors
        """

        providers = []
        for provider in provider_details:
            providers.append(provider)

        dns_details = {}
        error_msg = ''
        for provider_name in provider_details:
            access_urls = provider_details[provider_name].access_urls
            for access_url in access_urls:
                if 'operator_url' in access_url:
                    try:
                        msg = self._delete_cname_record(
                            access_url['operator_url'],
                            access_url.get('shared_ssl_flag', False))
                        if msg:
                            error_msg = error_msg + msg
                    except exc.NotFound as e:
                        LOG.error('Can not access the subdomain. Please make '
                                  'sure it exists and you have permissions '
                                  'to CDN subdomain {0}'.format(e))
                        error_msg = (error_msg + 'Can not access subdomain . '
                                     'Exception: {0}'.format(e))
                    except Exception as e:
                        LOG.error('Rackspace DNS Exception: {0}'.format(e))
                        error_msg = error_msg + 'Rackspace DNS ' \
                                                'Exception: {0}'.format(e)
                # format the error message for this provider
            if not error_msg:
                dns_details[provider_name] = self.responder.deleted({})

        # format the error message
        if error_msg:
            return self.responder.failed(providers, error_msg)

        return dns_details

    def _update_added_domains(self, responders, added_domains):
        """Update added domains."""

        # if no domains are added, return
        dns_details = {}
        if not added_domains:
            for responder in responders:
                for provider_name in responder:
                    dns_details[provider_name] = {'access_urls': []}
            return dns_details

        providers = []
        for responder in responders:
            for provider in responder:
                providers.append(provider)

        # gather the provider links for the added domains
        links = {}
        for responder in responders:
            for provider_name in responder:
                for link in responder[provider_name]['links']:
                    domain_added = (link['rel'] == 'access_url' and
                                    link['domain'] in added_domains)
                    if domain_added:
                        links[(link['domain'], link.get('certificate',
                                                        None))] = link['href']

        # create CNAME records for added domains
        try:
            dns_links = self._create_cname_records(links)
        except Exception as e:
            error_msg = 'Rackspace DNS Exception: {0}'.format(e)
            LOG.error(error_msg)
            return self.responder.failed(providers, error_msg)

        # gather the CNAMED links for added domains
        for responder in responders:
            for provider_name in responder:
                access_urls = []
                for link in responder[provider_name]['links']:
                    if link['domain'] in added_domains:
                        access_url = {
                            'domain': link['domain'],
                            'provider_url':
                                dns_links[(link['domain'],
                                           link.get('certificate', None)
                                           )]['provider_url'],
                            'operator_url':
                                dns_links[(link['domain'],
                                           link.get('certificate', None)
                                           )]['operator_url']}
                        # Need to indicate if this access_url is a shared ssl
                        # access url, since its has different shard_prefix and
                        # num_shard
                        if link.get('certificate', None) == 'shared':
                            access_url['shared_ssl_flag'] = True

                        access_urls.append(access_url)
                dns_details[provider_name] = {'access_urls': access_urls}
        return dns_details

    def _update_removed_domains(self, provider_details, removed_domains):
        """Update removed domains."""

        # if no domains are removed, return
        dns_details = {}
        if not removed_domains:
            for provider_name in provider_details:
                dns_details[provider_name] = {'access_urls': []}
            return dns_details

        providers = []
        for provider in provider_details:
            providers.append(provider)

        # delete the records for deleted domains
        error_msg = ''
        for provider_name in provider_details:
            provider_detail = provider_details[provider_name]
            for access_url in provider_detail.access_urls:
                if access_url['domain'] not in removed_domains:
                    continue
                try:
                    msg = self._delete_cname_record(access_url['operator_url'],
                                                    access_url.get(
                                                        'shared_ssl_flag',
                                                        False))
                    if msg:
                        error_msg = error_msg + msg
                except exc.NotFound as e:
                    LOG.error('Can not access the subdomain. Please make sure'
                              ' it exists and you have permissions to CDN '
                              'subdomain {0}'.format(e))
                    error_msg = (error_msg + 'Can not access subdomain. '
                                 'Exception: {0}'.format(e))
                except Exception as e:
                    LOG.error('Exception: {0}'.format(e))
                    error_msg = error_msg + 'Exception: {0}'.format(e)
            # format the success message for this provider
            if not error_msg:
                dns_details[provider_name] = self.responder.deleted({})

        # format the error message
        if error_msg:
            return self.responder.failed(providers, error_msg)

        return dns_details

    def update(self, service_old, service_updates, responders):
        """Update CNAME records for a service.

        :param service_old: previous service state
        :param service_updates: updates to service state
        :param responders: responders from providers

        :return dns_details: Map from provider_name to update errors
        """

        # get old domains
        old_domains = set()
        old_access_urls_map = {}
        provider_details = service_old.provider_details
        for provider_name in provider_details:
            provider_detail = provider_details[provider_name]
            access_urls = provider_detail.access_urls
            old_access_urls_map[provider_name] = {'access_urls': access_urls}
            for access_url in access_urls:
                if 'domain' in access_url:
                    old_domains.add(access_url['domain'])

        # if there is a provider error, don't try dns update
        for responder in responders:
            for provider_name in responder:
                if 'error' in responder[provider_name]:
                    return old_access_urls_map

        # get new_domains
        new_domains = set()
        for responder in responders:
            for provider_name in responder:
                links = responder[provider_name]['links']
                for link in links:
                    new_domains.add(link['domain'])

        # if domains have not been updated, return
        if not service_updates.domains:
            return old_access_urls_map

        # if the old set of domains is the same as new set of domains, return
        if old_domains == new_domains:
            return old_access_urls_map

        # get the list of added, removed and common domains
        added_domains = new_domains.difference(old_domains)
        removed_domains = old_domains.difference(new_domains)
        common_domains = new_domains.intersection(old_domains)

        # add new domains
        dns_links = self._update_added_domains(responders, added_domains)

        # remove CNAME records for deleted domains
        provider_details = service_old.provider_details
        self._update_removed_domains(provider_details, removed_domains)

        providers = []
        for responder in responders:
            for provider in responder:
                providers.append(provider)

        # in case of DNS error, return
        for provider_name in dns_links:
            if 'error' in dns_links[provider_name]:
                error_msg = dns_links[provider_name]['error_detail']
                return self.responder.failed(providers, error_msg)

        # gather the CNAMED links and remove stale links
        dns_details = {}
        for responder in responders:
            for provider_name in responder:
                provider_detail = service_old.provider_details[provider_name]
                old_access_urls = provider_detail.access_urls
                new_access_urls = dns_links[provider_name]['access_urls']
                access_urls = []
                for link in responder[provider_name]['links']:
                    if link['domain'] in removed_domains:
                        continue
                    elif link['domain'] in added_domains:
                        # iterate through new access urls and get access url
                        operator_url = None
                        for new_access_url in new_access_urls:
                            if new_access_url['domain'] == link['domain']:
                                operator_url = new_access_url['operator_url']
                                break
                        access_url = {
                            'domain': link['domain'],
                            'provider_url': link['href'],
                            'operator_url': operator_url}
                        # if it is a shared ssl access url, we need to store it
                        if new_access_url.get('shared_ssl_flag', False):
                            access_url['shared_ssl_flag'] = True
                        access_urls.append(access_url)
                    elif link['domain'] in common_domains:
                        # iterate through old access urls and get access url
                        operator_url = None
                        for old_access_url in old_access_urls:
                            if old_access_url['domain'] == link['domain']:
                                operator_url = old_access_url['operator_url']
                                break
                        access_url = {
                            'domain': link['domain'],
                            'provider_url': link['href'],
                            'operator_url': operator_url}
                        # if it is a shared ssl access url, we need to store it
                        if old_access_url.get('shared_ssl_flag', False):
                            access_url['shared_ssl_flag'] = True
                        access_urls.append(access_url)
                dns_details[provider_name] = {'access_urls': access_urls}

        return self.responder.updated(dns_details)
