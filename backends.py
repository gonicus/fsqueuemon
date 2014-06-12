# This file is part of fsqueuemon - https://github.com/gonicus/fsqueuemon
# Copyright (C) 2014 GONICUS GmbH, Germany - http://www.gonicus.de
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


from xmlrpclib import ServerProxy
from xml.etree.cElementTree import XML

import datetime

class CallcenterStatusBackend(object):

    domain = 'mydomain.example.com'

    def __init__(self, uri):
        self.server = ServerProxy(uri)

    def _parse_callcenter(self, apiresult):
        """Parse output of mod_callcenter's api output"""
        data = []
        lines = apiresult.splitlines()
        if lines:
            keys = lines[0].strip().split('|')
            for line in lines[1:]:
                fields = line.split('|')
                if len(fields) != len(keys):
                    continue
                entry = {}
                for i in range(0, len(keys)):
                    entry[keys[i]] = fields[i]
                data.append(entry)
        return data

    def _parse_xml(self, apiresult):
        data = []
        for row in XML(apiresult):
            data.append(dict([(e.tag, e.text) for e in row]))
        return data

    def _get_user_data(self, extension, data):
        presence_id = self.server.freeswitch.api('user_data', '%s@%s %s' % (extension, self.domain, data))
        if presence_id:
            return presence_id
        return None

    def get_agents(self):
        # Get list of all defined agents
        output = self.server.freeswitch.api('callcenter_config', 'agent list')
        agents = dict([(agent['name'], agent) for agent in self._parse_callcenter(output)])

        # Get tiers and update agent info
        output = self.server.freeswitch.api('callcenter_config', 'tier list')
        tiers = self._parse_callcenter(output)
        for tier in tiers:
            agent = agents.get(tier['agent'])
            if not agent:
                continue
            if not agent.get('queues'):
                agent['queues'] = []
            agent['queues'].append({'queue': tier['queue'], 'level': tier['level'], 'position': tier['position']})

        presence_table = {}
        # Get extension, real name and presence ID of logged in agents
        for agtid, agent in agents.iteritems():
            if agent['contact']:
                contact = agent['contact'].split('/')
                if contact[0].endswith('loopback'):
                    agent['extension'] = contact[1]
                    if contact[1] and contact[1][0] not in ('0', '9'):
                        realname = self._get_user_data(contact[1], 'var effective_caller_id_name')
                        if realname:
                            agent['realname'] = realname
                        presence_id = self._get_user_data(contact[1], 'var presence_id')
                        if presence_id:
                            agent['presence_id'] = presence_id
                            presence_table[presence_id] = agent

        # Get currently active channels
        output = self.server.freeswitch.api('show', 'channels as xml')
        channels = self._parse_xml(output)

        # Update presence state from active channels
        for channel in channels:
            if channel['presence_id'] in presence_table:
                presence_table[channel['presence_id']]['callstate'] = channel['callstate']
                presence_table[channel['presence_id']]['direction'] = 'caller' if channel['direction'] == 'inbound' else 'callee'

        return agents

    def get_queues(self):
        output = self.server.freeswitch.api('callcenter_config', 'queue list')
        queues = dict([(queue['name'], queue) for queue in self._parse_callcenter(output)])
        for queue in queues:
            output = self._parse_callcenter(self.server.freeswitch.api('callcenter_config', 'queue list members %s' % queue))
            output.sort(key=lambda m: m['system_epoch'])
            queues[queue]['members'] = output
            queues[queue]['waiting_count'] = len([x for x in output if x['state'] == 'Waiting'])

        return queues

