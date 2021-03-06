#coding:utf-8
# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from lxml import etree
from oslo.config import cfg
from webob import exc

from nova.api.openstack.compute.contrib import cloudpipe
from nova.api.openstack import wsgi
from nova.compute import utils as compute_utils
from nova import exception
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_network
from nova.tests import matchers
from nova import utils

CONF = cfg.CONF
CONF.import_opt('vpn_image_id', 'nova.cloudpipe.pipelib')


def fake_vpn_instance():
    return {
        'id': 7, 'image_ref': CONF.vpn_image_id, 'vm_state': 'active',
        'created_at': timeutils.parse_strtime('1981-10-20T00:00:00.000000'),
        'uuid': 7777, 'project_id': 'other',
    }


def compute_api_get_all_empty(context, search_opts=None):
    return []


def compute_api_get_all(context, search_opts=None):
        return [fake_vpn_instance()]


def utils_vpn_ping(addr, port, timoeout=0.05, session_id=None):
    return True


class CloudpipeTest(test.NoDBTestCase):

    def setUp(self):
        super(CloudpipeTest, self).setUp()
        self.controller = cloudpipe.CloudpipeController()
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all_empty)
        self.stubs.Set(utils, 'vpn_ping', utils_vpn_ping)

    def test_cloudpipe_list_no_network(self):

        def fake_get_nw_info_for_instance(instance):
            return {}

        self.stubs.Set(compute_utils, "get_nw_info_for_instance",
                       fake_get_nw_info_for_instance)
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all)
        req = fakes.HTTPRequest.blank('/v2/fake/os-cloudpipe')
        res_dict = self.controller.index(req)
        response = {'cloudpipes': [{'project_id': 'other',
                                    'instance_id': 7777,
                                    'created_at': '1981-10-20T00:00:00Z'}]}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_list(self):

        def network_api_get(context, network_id):
            self.assertEqual(context.project_id, 'other')
            return {'vpn_public_address': '127.0.0.1',
                    'vpn_public_port': 22}

        def fake_get_nw_info_for_instance(instance):
            return fake_network.fake_get_instance_nw_info(self.stubs)

        self.stubs.Set(compute_utils, "get_nw_info_for_instance",
                       fake_get_nw_info_for_instance)
        self.stubs.Set(self.controller.network_api, "get",
                       network_api_get)
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all)
        req = fakes.HTTPRequest.blank('/v2/fake/os-cloudpipe')
        res_dict = self.controller.index(req)
        response = {'cloudpipes': [{'project_id': 'other',
                                    'internal_ip': '192.168.1.100',
                                    'public_ip': '127.0.0.1',
                                    'public_port': 22,
                                    'state': 'running',
                                    'instance_id': 7777,
                                    'created_at': '1981-10-20T00:00:00Z'}]}
        self.assertThat(res_dict, matchers.DictMatches(response))

    def test_cloudpipe_create(self):
        def launch_vpn_instance(context):
            return ([fake_vpn_instance()], 'fake-reservation')

        self.stubs.Set(self.controller.cloudpipe, 'launch_vpn_instance',
                       launch_vpn_instance)
        body = {'cloudpipe': {'project_id': 1}}
        req = fakes.HTTPRequest.blank('/v2/fake/os-cloudpipe')
        res_dict = self.controller.create(req, body)

        response = {'instance_id': 7777}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_create_no_networks(self):
        def launch_vpn_instance(context):
            raise exception.NoMoreNetworks

        self.stubs.Set(self.controller.cloudpipe, 'launch_vpn_instance',
                       launch_vpn_instance)
        body = {'cloudpipe': {'project_id': 1}}
        req = fakes.HTTPRequest.blank('/v2/fake/os-cloudpipe')
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_cloudpipe_create_already_running(self):
        def launch_vpn_instance(*args, **kwargs):
            self.fail("Method should not have been called")

        self.stubs.Set(self.controller.cloudpipe, 'launch_vpn_instance',
                       launch_vpn_instance)
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all)
        body = {'cloudpipe': {'project_id': 1}}
        req = fakes.HTTPRequest.blank('/v2/fake/os-cloudpipe')
        res_dict = self.controller.create(req, body)
        response = {'instance_id': 7777}
        self.assertEqual(res_dict, response)


class CloudpipesXMLSerializerTest(test.NoDBTestCase):
    def test_default_serializer(self):
        serializer = cloudpipe.CloudpipeTemplate()
        exemplar = dict(cloudpipe=dict(instance_id='1234-1234-1234-1234'))
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)
        self.assertEqual('cloudpipe', tree.tag)
        for child in tree:
            self.assertIn(child.tag, exemplar['cloudpipe'])
            self.assertEqual(child.text, exemplar['cloudpipe'][child.tag])

    def test_index_serializer(self):
        serializer = cloudpipe.CloudpipesTemplate()
        exemplar = dict(cloudpipes=[
                dict(
                        project_id='1234',
                        public_ip='1.2.3.4',
                        public_port='321',
                        instance_id='1234-1234-1234-1234',
                        created_at=timeutils.isotime(),
                        state='running'),
                dict(
                        project_id='4321',
                        public_ip='4.3.2.1',
                        public_port='123',
                        state='pending')])
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)
        self.assertEqual('cloudpipes', tree.tag)
        self.assertEqual(len(exemplar['cloudpipes']), len(tree))
        for idx, cl_pipe in enumerate(tree):
            kp_data = exemplar['cloudpipes'][idx]
            for child in cl_pipe:
                self.assertIn(child.tag, kp_data)
                self.assertEqual(child.text, kp_data[child.tag])

    def test_deserializer(self):
        deserializer = wsgi.XMLDeserializer()
        exemplar = dict(cloudpipe=dict(project_id='4321'))
        intext = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                  '<cloudpipe><project_id>4321</project_id></cloudpipe>')
        result = deserializer.deserialize(intext)['body']
        self.assertEqual(result, exemplar)
