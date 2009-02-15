# Copyright (C) 2008 One Laptop Per Child
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
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import dbus
from gettext import gettext as _
import gconf

_NM_SERVICE = 'org.freedesktop.NetworkManager'
_NM_PATH = '/org/freedesktop/NetworkManager'
_NM_IFACE = 'org.freedesktop.NetworkManager'

KEYWORDS = ['network', 'jabber', 'radio', 'server']

class ReadError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

def get_jabber():
    client = gconf.client_get_default()
    return client.get_string('/desktop/sugar/collaboration/jabber_server')

def print_jabber():
    print get_jabber()

def set_jabber(server):
    """Set the jabber server
    server : e.g. 'olpc.collabora.co.uk'
    """
    client = gconf.client_get_default()
    client.set_string('/desktop/sugar/collaboration/jabber_server', server)

    _restart_jabber()
    return 0

def _restart_jabber():
    """Call Sugar Presence Service to restart Telepathy CMs.

    This allows restarting the jabber server connection when we change it.
    """
    _PS_SERVICE = "org.laptop.Sugar.Presence"
    _PS_INTERFACE = "org.laptop.Sugar.Presence"
    _PS_PATH = "/org/laptop/Sugar/Presence"
    bus = dbus.SessionBus()
    try:
        ps = dbus.Interface(bus.get_object(_PS_SERVICE, _PS_PATH), 
                            _PS_INTERFACE)
    except dbus.DBusException:
        raise ReadError('%s service not available' % _PS_SERVICE)
    ps.RestartServerConnection()

def get_radio():
    bus = dbus.SystemBus()
    try:
        obj = bus.get_object(_NM_SERVICE, _NM_PATH)
        nm_props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
    except dbus.DBusException:
        raise ReadError('%s service not available' % _NM_SERVICE)

    state = nm_props.Get(_NM_IFACE, 'WirelessEnabled')
    if state in (0, 1):
        return state
    else:
        raise ReadError(_('State is unknown.'))

def print_radio():
    print ('off', 'on')[get_radio()]
    
def set_radio(state):
    """Turn Radio 'on' or 'off'
    state : 'on/off'
    """    
    if state == 'on' or state == 1:
        bus = dbus.SystemBus()
        try:
            obj = bus.get_object(_NM_SERVICE, _NM_PATH)
            nm_props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
        except dbus.DBusException:
            raise ReadError('%s service not available' % _NM_SERVICE)
        nm_props.Set(_NM_IFACE, 'WirelessEnabled', True)
    elif state == 'off' or state == 0:
        bus = dbus.SystemBus()
        try:
            obj = bus.get_object(_NM_SERVICE, _NM_PATH)
            nm_props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
        except dbus.DBusException:
            raise ReadError('%s service not available' % _NM_SERVICE)
        nm_props.Set(_NM_IFACE, 'WirelessEnabled', False)
    else:
        raise ValueError(_("Error in specified radio argument use on/off."))

    return 0

def clear_registration():
    """Clear the registration with the schoolserver
    """
    client = gconf.client_get_default()
    client.set_string('/desktop/sugar/backup_url', '')
    return 1

def clear_networks():
    """Clear saved passwords and network configurations.
    """
    pass

def get_publish_information():
    client = gconf.client_get_default()
    publish = client.get_bool('/desktop/sugar/collaboration/publish_gadget')
    return publish
	
def print_publish_information():
    print get_publish_information()

def set_publish_information(value):
    """ If set to true, Sugar will make you searchable for 
    the other users of the Jabber server.
    value: 0/1
    """
    try:
        value = (False, True)[int(value)]
    except:
        raise ValueError(_("Error in specified argument use 0/1."))

    client = gconf.client_get_default()
    client.set_bool('/desktop/sugar/collaboration/publish_gadget', value)
    return 0