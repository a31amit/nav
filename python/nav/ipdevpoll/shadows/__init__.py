#
# Copyright (C) 2009-2012 UNINETT AS
#
# This file is part of Network Administration Visualized (NAV).
#
# NAV is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.  You should have received a copy of the GNU General Public
# License along with NAV. If not, see <http://www.gnu.org/licenses/>.
#
"""Shadow model classes.

This module defines Shadow classes for use in ipdevpoll's storage system.  A
Shadow object will mimic a Django model object, but will not be a "live
object", in the sense that access to member attributes will not result in
database I/O.

"""
import datetime
import IPy

from django.db.models import Q

from nav.models import manage, oid
from nav.models.event import EventQueue as Event, EventQueueVar as EventVar

from nav.ipdevpoll.storage import MetaShadow, Shadow
from nav.ipdevpoll import descrparsers
from nav.ipdevpoll import utils
from nav.ipdevpoll import db

from .netbox import Netbox
from .interface import Interface, InterfaceStack
from .swportblocked import SwPortBlocked
from .cam import Cam
from .adjacency import AdjacencyCandidate, UnrecognizedNeighbor

PREFIX_AUTHORITATIVE_CATEGORIES = ('GW', 'GSW')

# Shadow classes.  Not all of these will be used to store data, but
# may be used to retrieve and cache existing database records.

# Shadow classes usually don't need docstrings - these can be found in the
# Django models being shadowed:
# pylint: disable=C0111

class NetboxType(Shadow):
    __shadowclass__ = manage.NetboxType
    __lookups__ = ['sysobjectid']

    def get_enterprise_id(self):
        """Returns the type's enterprise ID as an integer.

        The type's sysobjectid should always start with
        SNMPv2-SMI::enterprises (1.3.6.1.4.1).  The next OID element will be
        an enterprise ID, while the remaining elements will describe the type
        specific to the vendor.

        :returns: A long integer if the type has a valid enterprise id, None
                  otherwise.

        """
        prefix = u"1.3.6.1.4.1."
        if self.sysobjectid.startswith(prefix):
            specific = self.sysobjectid[len(prefix):]
            enterprise = specific.split('.')[0]
            return long(enterprise)

class NetboxInfo(Shadow):
    __shadowclass__ = manage.NetboxInfo
    __lookups__ = [('netbox', 'key', 'variable')]

    @classmethod
    def get_dependencies(cls):
        """Fakes a dependency to all Shadow subclasses.

        We do this to ensure NetboxInfo is always the last table to be updated
        by a job.

        Often, this table is used to store timestamps of successful jobs, but
        with no other real dependencies than Netbox it would be saved before
        most of the other container objects are saved. Since not all the data
        is stored in a single transaction, storing timestamps in NetboxInfo
        may indicate a success where there was in reality a failure due to a
        database problem that occurred after NetboxInfo was updated.

        """

        return MetaShadow.shadowed_classes.values()

class Vendor(Shadow):
    __shadowclass__ = manage.Vendor

# pylint is unable to see which members are created dynamically by metaclass:
# pylint: disable=E0203,W0201
class Module(Shadow):
    __shadowclass__ = manage.Module
    __lookups__ = [('netbox', 'device'), ('netbox', 'name')]

    def prepare(self, containers):
        self._fix_binary_garbage()
        self._fix_missing_name()
        self._resolve_duplicate_serials()
        self._resolve_duplicate_names()

    def _fix_binary_garbage(self):
        """Fixes string attributes that appear as binary garbage."""

        if utils.is_invalid_utf8(self.model):
            self._logger.warn("Invalid value for model: %r", self.model)
            self.model = repr(self.model)

    def _fix_missing_name(self):
        if not self.name and self.device and self.device.serial:
            self.name = "S/N %s" % self.device.serial

    def _resolve_duplicate_serials(self):
        """Attempts to solve serial number conflicts before savetime.

        Specifically, if another Module in the database is registered with the
        same serial number as this one, we attach an empty device to the other
        module.

        """
        if not self.device or not self.device.serial:
            return

        myself = self.get_existing_model()
        try:
            other = manage.Module.objects.get(
                device__serial=self.device.serial)
        except manage.Module.DoesNotExist:
            return

        if other != myself:
            myself = myself or self
            self._logger.warning(
                "Serial number conflict, attempting peaceful resolution (%s): "
                "I am %r (%s) at %s (id: %s) <-> "
                "other is %r (%s) at %s (id: %s)",
                self.device.serial,
                self.name, self.description, myself.netbox.sysname, myself.id,
                other.name, other.description, other.netbox.sysname, other.id)
            new_device = manage.Device()
            new_device.save()
            other.device = new_device
            other.save()

    def _resolve_duplicate_names(self):
        """Attempts to solve module naming conflicts inside the same chassis.

        If two modules physically switch slots in a chassis, they will be
        recognized by their serial numbers, but their names will likely be
        swapped.

        Module names must be unique within a chassis, so if another module on
        this netbox has the same name as us, we need to do something about the
        other module's name before our own to avoid a database integrity
        error.

        """
        other = self._find_name_duplicates()
        if other:
            self._logger.warning(
                "modules appear to have been swapped inside same chassis (%s): "
                "%s (%s) <-> %s (%s)",
                other.netbox.sysname,
                self.name, self.device.serial,
                other.name, other.device.serial)

            other.name = u"%s (%s)" % (other.name, other.device.serial)
            other.save()


    def _find_name_duplicates(self):
        myself_in_db = self.get_existing_model()

        same_name_modules = manage.Module.objects.filter(
            netbox__id = self.netbox.id,
            name = self.name)

        if myself_in_db:
            same_name_modules = same_name_modules.exclude(
                id = myself_in_db.id)

        other = same_name_modules.select_related('device', 'netbox')

        return other[0] if other else None

    @classmethod
    def _make_modulestate_event(cls, django_module):
        event = Event()
        event.source_id = 'ipdevpoll'
        event.target_id = 'eventEngine'
        event.device = django_module.device
        event.netbox = django_module.netbox
        event.subid = unicode(django_module.id)
        event.event_type_id = 'moduleState'
        return event

    @classmethod
    def _dispatch_down_event(cls, django_module):
        event = cls._make_modulestate_event(django_module)
        event.state = event.STATE_START
        event.save()

    @classmethod
    def _dispatch_up_event(cls, django_module):
        event = cls._make_modulestate_event(django_module)
        event.state = event.STATE_END
        event.save()

    @classmethod
    def _handle_missing_modules(cls, containers):
        """Handles modules that have gone missing from a device."""
        netbox = containers.get(None, Netbox)
        all_modules = manage.Module.objects.filter(netbox__id = netbox.id)
        modules_up = all_modules.filter(up=manage.Module.UP_UP)
        modules_down = all_modules.filter(up=manage.Module.UP_DOWN)

        collected_modules = containers[Module].values()
        collected_module_pks = [m.id for m in collected_modules if m.id]

        missing_modules = modules_up.exclude(id__in=collected_module_pks)
        reappeared_modules = modules_down.filter(id__in=collected_module_pks)

        if missing_modules:
            shortlist = ", ".join(m.name for m in missing_modules)
            cls._logger.info("%d modules went missing on %s (%s)",
                             netbox.sysname, len(missing_modules), shortlist)
            for module in missing_modules:
                cls._dispatch_down_event(module)

        if reappeared_modules:
            shortlist = ", ".join(m.name for m in reappeared_modules)
            cls._logger.info("%d modules reappeared on %s (%s)",
                             netbox.sysname, len(reappeared_modules),
                             shortlist)
            for module in reappeared_modules:
                cls._dispatch_up_event(module)


    @classmethod
    def cleanup_after_save(cls, containers):
        cls._handle_missing_modules(containers)
        return super(Module, cls).cleanup_after_save(containers)


class Device(Shadow):
    __shadowclass__ = manage.Device
    __lookups__ = ['serial']

    def prepare(self, containers):
        self._fix_binary_garbage()
        self._find_existing_netbox_device(containers)

    def _fix_binary_garbage(self):
        """Fixes version strings that appear as binary garbage."""

        for attr in ('hardware_version',
                     'software_version',
                     'firmware_version',
                     'serial'):
            value = getattr(self, attr)
            if utils.is_invalid_utf8(value):
                self._logger.warn("Invalid value for %s: %r",
                                  attr, value)
                setattr(self, attr, repr(value))
        self.clear_cached_objects()

    def _find_existing_netbox_device(self, containers):
        """Ensures that we re-use the existing Device record for a Netbox when
        the job didn't collect a serial number for the chassis.

        """
        if 'serial' in self.get_touched():
            return

        netbox = containers.get(None, Netbox)
        if netbox and netbox.device is self:
            try:
                device = manage.Device.objects.get(netbox__id=netbox.id)
            except manage.Device.DoesNotExist:
                return
            else:
                self.set_existing_model(device)


class Location(Shadow):
    __shadowclass__ = manage.Location

class Room(Shadow):
    __shadowclass__ = manage.Room

class Category(Shadow):
    __shadowclass__ = manage.Category

class Organization(Shadow):
    __shadowclass__ = manage.Organization

class Usage(Shadow):
    __shadowclass__ = manage.Usage

class Vlan(Shadow):
    __shadowclass__ = manage.Vlan

    def save(self, containers):
        prefixes = self._get_my_prefixes(containers)
        if prefixes:
            mdl = self.get_existing_model(containers)
            if mdl and mdl.net_type_id == 'scope':
                self._logger.warning(
                    "some interface claims to be on a scope prefix, not "
                    "changing vlan details. attached prefixes: %r",
                    [pfx.net_address for pfx in prefixes])
                for pfx in prefixes:
                    pfx.vlan = mdl
                return
            else:
                if (self.organization
                    and not self.organization.get_existing_model()):
                    self._logger.warning("ignoring unknown organization id %r",
                                         self.organization.id)
                    self.organization = None

                if (self.usage
                    and not self.usage.get_existing_model()):
                    self._logger.warning("ignoring unknown usage id %r",
                                         self.usage.id)
                    self.usage = None

                super(Vlan, self).save(containers)
        else:
            self._logger.debug("no associated prefixes, not saving: %r", self)

    def _get_my_prefixes(self, containers):
        """Get a list of Prefix shadow objects that point to this Vlan."""
        if Prefix in containers:
            all_prefixes = containers[Prefix].values()
            my_prefixes = [prefix for prefix in all_prefixes
                           if prefix.vlan is self]
            return my_prefixes
        else:
            return []

    def _get_vlan_from_my_prefixes(self, containers):
        """Find and return an existing vlan any shadow prefix object pointing
        to this Vlan.

        """
        my_prefixes = self._get_my_prefixes(containers)
        for prefix in my_prefixes:
            live_prefix = prefix.get_existing_model()
            if live_prefix and live_prefix.vlan_id:
                # We just care about the first associated prefix we found
                self._logger.debug(
                    "_get_vlan_from_my_prefixes: selected prefix "
                    "%s for possible vlan match for %r (%s), "
                    "pre-existing is %r",
                    live_prefix.net_address, self, id(self),
                    live_prefix.vlan)
                return live_prefix.vlan

    def get_existing_model(self, containers=None):
        """Finds pre-existing Vlan object using custom logic.

        This is complicated because of the relationship between Prefix and
        Vlan, and the fact that multiple vlans with the same vlan number may
        exist, and even Vlan entries without a number.

        If we have a known netident and find an existing record with the same
        vlan value (either a number or NULL) and netident, they are considered
        the same.

        Otherwise, we consider the prefixes that are associated with this vlan.
        If these prefixes already exist in the database, they are likely
        connected to the existing vlan object that we should update.

        If all else fails, a new record is created.

        """
        # Only lookup if primary key isn't already set.
        if self.id:
            return super(Vlan, self).get_existing_model(containers)

        if self.net_ident:
            vlans = manage.Vlan.objects.filter(vlan=self.vlan,
                                               net_ident=self.net_ident)
            if vlans:
                self._logger.debug(
                    "get_existing_model: %d matches found for "
                    "vlan+net_ident: %r",
                    len(vlans), self)
                return vlans[0]

        vlan = self._get_vlan_from_my_prefixes(containers)
        if vlan:
            # Only claim to be the same Vlan object if the vlan number is the
            # same, or the pre-existing object has no Vlan number.
            if vlan.vlan is None or vlan.vlan == self.vlan:
                return vlan

    def _log_if_multiple_prefixes(self, prefix_containers):
        if len(prefix_containers) > 1:
            self._logger.debug("multiple prefixes for %r: %r",
                self, [p.net_address for p in prefix_containers])


    def _guesstimate_net_type(self, containers):
        """Guesstimates a net type for this VLAN, based on its prefixes.

        Various algorithms may be used (and the database may be queried).

        Returns:

          A NetType storage container, suitable for assignment to
          Vlan.net_type.

        """
        prefix_containers = self._get_my_prefixes(containers)
        self._log_if_multiple_prefixes(prefix_containers)

        if prefix_containers:
            # prioritize ipv4 prefixes, as the netmasks are more revealing
            prefix_containers.sort(
                key=lambda p: IPy.IP(p.net_address).version())
            prefix = IPy.IP(prefix_containers[0].net_address)
        else:
            return NetType.get('unknown')

        netbox = containers.get(None, Netbox)
        net_type = 'lan'
        router_count = self._get_router_count_for_prefix(prefix, netbox.id)

        if prefix.version() == 6 and prefix.prefixlen() == 128:
            net_type = 'loopback'
        elif prefix.version() == 4:
            if prefix.prefixlen() == 32:
                net_type = 'loopback'
            elif prefix.prefixlen() in (30, 31):
                net_type = router_count == 1 and 'elink' or 'link'
        if router_count > 2:
            net_type = 'core'
        elif router_count == 2:
            net_type = 'link'

        return NetType.get(net_type)

    @staticmethod
    def _get_router_count_for_prefix(net_address, include_netboxid=None):
        """Returns the number of routers attached to a prefix.

        :param net_address: a prefix network address
        :param include_netboxid: count the netbox with this id as a router for
                                 the prefix, no matter what the db might say
                                 about it.
        :returns: an integer count of routers for `net_address`

        """
        address_filter = Q(interface__gwportprefix__prefix__net_address=
                           str(net_address))
        if include_netboxid:
            address_filter = address_filter | Q(id=include_netboxid)

        router_count = manage.Netbox.objects.filter(
            address_filter,
            category__id__in=('GW', 'GSW')
            )
        return router_count.distinct().count()

    def prepare(self, containers):
        """Prepares this VLAN object for saving.

        The data stored in a VLAN object consists much of what can be found
        from other objects, such as interfaces and prefixes, so the logic in
        here can becore rather involved.

        """
        if not self.net_type or self.net_type.id == 'unknown':
            net_type = self._guesstimate_net_type(containers)
            if net_type:
                self.net_type = net_type

class Prefix(Shadow):
    __shadowclass__ = manage.Prefix
    __lookups__ = [('net_address', 'vlan'), 'net_address']

    def save(self, containers):
        if self.get_existing_model():  # I already exist in the db
            netbox = containers.get(None, Netbox).get_existing_model()
            if netbox.category_id not in PREFIX_AUTHORITATIVE_CATEGORIES:
                self._logger.debug(
                    "not updating existing prefix %s for box of category %s",
                    self.net_address, netbox.category_id)
                return
        return super(Prefix, self).save(containers)

class GwPortPrefix(Shadow):
    __shadowclass__ = manage.GwPortPrefix
    __lookups__ = ['gw_ip']

    @classmethod
    def cleanup_after_save(cls, containers):
        cls._delete_missing_addresses(containers)

    @classmethod
    @db.autocommit
    def _delete_missing_addresses(cls, containers):
        missing_addresses = cls._get_missing_addresses(containers)
        gwips = [row['gw_ip'] for row in missing_addresses.values('gw_ip')]
        if len(gwips) < 1:
            return

        netbox = containers.get(None, Netbox).get_existing_model()
        cls._logger.info("deleting %d missing addresses from %s: %s",
                         len(gwips), netbox.sysname, ", ".join(gwips))

        missing_addresses.delete()

    @classmethod
    @db.autocommit
    def _get_missing_addresses(cls, containers):
        found_addresses = [g.gw_ip
                           for g in containers[cls].values()]
        netbox = containers.get(None, Netbox).get_existing_model()
        missing_addresses = manage.GwPortPrefix.objects.filter(
            interface__netbox=netbox).exclude(
            gw_ip__in=found_addresses)
        return missing_addresses

    def _parse_description(self, containers):
        """Parses router port descriptions to find a suitable Organization,
        netident, usageid and description for this vlan.

        """
        if not self._are_description_variables_present():
            return

        data = self._parse_description_with_all_parsers()
        if not data:
            self._logger.debug("ifalias did not match any known router port "
                               "description conventions: %s",
                               self.interface.ifalias)
            self.prefix.vlan.netident = self.interface.ifalias
            return

        self._update_with_parsed_description_data(data, containers)

    def _are_description_variables_present(self):
        return self.interface and \
            self.interface.netbox and \
            self.interface.ifalias and \
            self.prefix and \
            self.prefix.vlan

    def _parse_description_with_all_parsers(self):
        for parse in (descrparsers.parse_ntnu_convention,
                      descrparsers.parse_uninett_convention):
            data = parse(self.interface.netbox.sysname, self.interface.ifalias)
            if data:
                return data

    def _update_with_parsed_description_data(self, data, containers):
        vlan = self.prefix.vlan
        if data.get('net_type', None):
            vlan.net_type = NetType.get(data['net_type'].lower())
        if data.get('netident', None):
            vlan.net_ident = data['netident']
        if data.get('usage', None):
            vlan.usage = containers.factory(data['usage'], Usage)
            vlan.usage.id = data['usage']
        if data.get('comment', None):
            vlan.description = data['comment']
        if data.get('org', None):
            vlan.organization = containers.factory(data['org'], Organization)
            vlan.organization.id = data['org']

    def prepare(self, containers):
        self._parse_description(containers)

class NetType(Shadow):
    __shadowclass__ = manage.NetType

    @classmethod
    def get(cls, net_type_id):
        """Creates a NetType container for the given net_type id."""
        ntype = cls()
        ntype.id = net_type_id
        return ntype


class SwPortVlan(Shadow):
    __shadowclass__ = manage.SwPortVlan

class Arp(Shadow):
    __shadowclass__ = manage.Arp

    def save(self, containers):
        if not self.id:
            return super(Arp, self).save(containers)

        attrs = dict((attr, getattr(self, attr))
                     for attr in self.get_touched()
                     if attr != 'id')
        if attrs:
            myself = manage.Arp.objects.filter(id=self.id)
            myself.update(**attrs)

class SwPortAllowedVlan(Shadow):
    __shadowclass__ = manage.SwPortAllowedVlan
    __lookups__ = ['interface']

class Sensor(Shadow):
    __shadowclass__ = manage.Sensor
    __lookups__ = [('netbox', 'internal_name', 'mib')]

    @classmethod
    def cleanup_after_save(cls, containers):
        cls._delete_missing_sensors(containers)
        
    @classmethod
    @db.autocommit
    def _delete_missing_sensors(cls, containers):
        missing_sensors = cls._get_missing_sensors(containers)
        sensor_names = [row['internal_name']
                            for row in missing_sensors.values('internal_name')]
        if len(missing_sensors) < 1:
            return
        netbox = containers.get(None, Netbox)
        cls._logger.debug('Deleting %d missing sensors from %s: %s',
                          len(sensor_names), netbox.sysname,
                          ", ".join(sensor_names))
        missing_sensors.delete()

    @classmethod
    @db.autocommit
    def _get_missing_sensors(cls, containers):
        found_sensor_pks = [sensor.id for sensor in containers[cls].values()]
        netbox = containers.get(None, Netbox)
        missing_sensors = manage.Sensor.objects.filter(
            netbox=netbox.id).exclude(pk__in=found_sensor_pks)
        return missing_sensors
        
class PowerSupplyOrFan(Shadow):
    __shadowclass__ = manage.PowerSupplyOrFan
    __lookups__ = [('netbox', 'name')]

    @classmethod
    def cleanup_after_save(cls, containers):
        cls._delete_missing_psus_and_fans(containers)

    @classmethod
    @db.autocommit
    def _delete_missing_psus_and_fans(cls, containers):
        missing_psus_and_fans = cls._get_missing_psus_and_fans(containers)
        psu_and_fan_names = [row['name']
                             for row in missing_psus_and_fans.values('name')]
        if len(missing_psus_and_fans) < 1:
            return
        netbox = containers.get(None, Netbox)
        cls._logger.debug('Deleting %d missing psus and fans from %s: %s',
            len(psu_and_fan_names), netbox.sysname,
            ", ".join(psu_and_fan_names))
        missing_psus_and_fans.delete()

    @classmethod
    @db.autocommit
    def _get_missing_psus_and_fans(cls, containers):
        found_psus_and_fans_pks = [psu_fan.id
                                   for psu_fan in containers[cls].values()]
        netbox = containers.get(None, Netbox)
        missing_psus_and_fans = manage.PowerSupplyOrFan.objects.filter(
            netbox=netbox.id).exclude(pk__in=found_psus_and_fans_pks)
        return missing_psus_and_fans
    