# Copyright 2013 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

import logging

from ..config import config
from ..netconfpersistence import RunningConfig
from ..netinfo import NetInfo, getIfaceCfg
from . import expose
from .upgrade import upgrade


UPGRADE_NAME = 'UnifiedPersistence'


@upgrade(UPGRADE_NAME)
def run():
    networks, bondings = _getNetInfo()
    logging.debug('%s upgrade persisting networks %s and bondings %s',
                  UPGRADE_NAME, networks, bondings)
    _persist(networks, bondings)


def _toIfcfgFormat(value):
    filter = {'on': 'yes', 'off': 'no'}
    # If value is in the dict and hashable - Get its filtered value.
    # Otherwise: Return the original value
    try:
        return filter.get(value, value)
    except TypeError:
        return value


def _getNetInfo():
    def _processNetworks(netinfo):
        networks = {}
        whitelist = ['bridged', 'mtu', 'qosInbound', 'qosOutbound', 'stp']
        toLower = ['True', 'False', 'None']
        toUpper = ['stp']

        for network, netParams in netinfo.networks.iteritems():
            networks[network] = {}

            # Copy key/value pairs from netinfo to unified if name matches
            for k, v in netParams.iteritems():
                if k in whitelist and v != "":
                    k = k.upper() if k in toUpper else k
                    v = str(_toIfcfgFormat(v))
                    v = v.lower() if v in toLower else v
                    networks[network][k] = v

            # Determine devices: nic/bond -> vlan -> bridge
            physicalDevice = "".join(netParams['ports']) if \
                netParams.get('ports') else netParams.get('interface')
            topLevelDevice = netParams['iface'] if \
                netParams['bridged'] else physicalDevice

            # Copy ip addressing information
            bootproto = str(getIfaceCfg(topLevelDevice).get('BOOTPROTO'))
            if bootproto == 'dhcp':
                networks[network]['bootproto'] = bootproto
            else:
                if netParams['addr'] != '':
                    networks[network]['ipaddr'] = netParams['addr']
                if netParams['netmask'] != '':
                    networks[network]['netmask'] = netParams['netmask']
                if netParams['gateway'] != '':
                    networks[network]['gateway'] = netParams['gateway']

            # What if the 'physical device' is actually a VLAN?
            if physicalDevice in netinfo.vlans:
                vlanDevice = physicalDevice
                networks[network]['vlan'] = \
                    str(netinfo.vlans[vlanDevice]['vlanid'])
                # The 'new' physical device is the VLAN's device
                physicalDevice = netinfo.vlans[vlanDevice]['iface']

            # Is the physical device a bond or a nic?
            if physicalDevice in netinfo.bondings:
                networks[network]['bonding'] = physicalDevice
            else:
                networks[network]['nic'] = physicalDevice

        return networks

    def _processBondings(netinfo):
        bondings = {}
        for bonding, bondingParams in netinfo.bondings.iteritems():
            # If the bond is unused, skip it
            if not bondingParams['slaves']:
                continue

            bondings[bonding] = {'nics': bondingParams['slaves']}
            bondingOptions = getIfaceCfg(bonding). \
                get('BONDING_OPTS')
            if bondingOptions:
                bondings[bonding]['options'] = bondingOptions

        return bondings

    netinfo = NetInfo()
    return _processNetworks(netinfo), _processBondings(netinfo)


def _persist(networks, bondings):
    runningConfig = RunningConfig()
    runningConfig.delete()

    for network, attributes in networks.iteritems():
        runningConfig.setNetwork(network, attributes)

    for bond, attributes in bondings.iteritems():
        runningConfig.setBonding(bond, attributes)

    runningConfig.save()
    runningConfig.store()


def isNeeded():
    return config.get('vars', 'persistence') == 'unified'


@expose('upgrade-to-unified-persistence')
def unified_persistence():
    """
    Upgrade host networking persistence from ifcfg to unified if the
    persistence model is set as unified in /usr/lib64/python2.X/site-packages/
    vdsm/config.py
    """
    if isNeeded():
        return run()
    return 0
