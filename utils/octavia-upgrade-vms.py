# Copyright 2016 Catalyst IT
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

import argparse
import six
import sys
import time

from neutronclient.common import exceptions as neutron_client_exceptions
from oslo_config import cfg
from oslo_log import log as logging
import sqlalchemy as sa

from octavia.common import clients
from octavia.common import constants
from octavia.common import service
from octavia.db import api as db_api
from octavia.db import models
from octavia.db import repositories as repo
from octavia.compute.drivers import nova_driver
from octavia.network.drivers.neutron import allowed_address_pairs

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

cli_opts = [
    cfg.BoolOpt('dryrun',
                default=False,
                help='Just print logs.'),
]

CONF.register_cli_opts(cli_opts)


def get_spare_amphoras(session):
    with session.begin(subtransactions=True):
        amps = session.query(models.Amphora).filter_by(
            status=constants.AMPHORA_READY, load_balancer_id=None).all()

    return amps


def delete_amp(nova_manager, session, amp_repo, amphealth_repo, amp):
    LOG.debug("Deleting vm: %s, amp: %s.", amp.compute_id, amp.id)
    if not CONF.dryrun:
        amphealth_repo.delete(session, amphora_id=amp.id)
        amp_repo.delete(session, id=amp.id)
        nova_manager.delete(amp.compute_id)


def check_spare_pool(amp_repo, session):
    retries = 90

    for a in six.moves.xrange(retries):
        conf_spare_cnt = CONF.house_keeping.spare_amphora_pool_size
        curr_spare_amps = get_spare_amphoras(session)
        LOG.debug("Required spare amphora count: %d, Current spare amphora "
                  "count: %d", conf_spare_cnt, len(curr_spare_amps))

        if len(curr_spare_amps) < conf_spare_cnt:
            if a >= retries:
                raise Exception("Timeout when waiting for spare pool to "
                                "fill up.")
            time.sleep(10)
        else:
            amp_ids = [amp.id for amp in curr_spare_amps]
            with session.begin(subtransactions=True):
                amp_health_cnt = session.query(models.AmphoraHealth).filter(
                    models.AmphoraHealth.amphora_id.in_(amp_ids)).count()

            if amp_health_cnt >= len(curr_spare_amps):
                return

            if a >= retries:
                raise Exception(
                    "Timeout when waiting for spare pool to fill up."
                )

            LOG.debug(
                "Waiting for healthcheck of amphorae vms in spare pool, "
                "%s left.", len(curr_spare_amps) - amp_health_cnt)

            time.sleep(10)


def get_amps(session, lbid_list=[], role=constants.ROLE_BACKUP):
    with session.begin(subtransactions=True):
        criterion = sa.and_(
            models.Amphora.status == constants.AMPHORA_ALLOCATED,
            models.Amphora.role == role,
            models.Amphora.vrrp_interface != None
        )

        if lbid_list:
            criterion = sa.and_(
                criterion,
                models.Amphora.load_balancer_id.in_(lbid_list)
            )

        amps = session.query(models.Amphora).filter(criterion).all()

    return amps


def wait_amps_failover(session, lb_amp_dict, role=constants.ROLE_BACKUP):
    LOG.debug("Waiting for %s amps failover...", role)

    retries = 180

    for a in six.moves.xrange(retries):
        lbid_list = list(lb_amp_dict)
        amps = get_amps(session, lbid_list, role)
        LOG.debug("%s amphorae vms ready.", len(amps))

        for amp in amps:
            if amp.id != lb_amp_dict[amp.load_balancer_id]:
                lb_amp_dict.pop(amp.load_balancer_id)

                LOG.debug("The %s amp vm for loadbalancer %s is created. "
                          "Still have %s left.", role, amp.load_balancer_id,
                          len(lb_amp_dict))

        if lb_amp_dict:
            if a >= retries:
                if CONF.dryrun:
                    return
                raise Exception("Timeout when waiting for amps failover.")
            time.sleep(10)
        else:
            return


def get_vm_mgmt_port(net_driver, vmid, lb_net_ip):
    interfaces = net_driver.get_plugged_networks(compute_id=vmid)

    for interface in interfaces:
        for ip in interface.fixed_ips:
            if ip.ip_address == lb_net_ip:
                LOG.debug("\tFound management port %s for vm %s.",
                          interface.port_id, vmid)
                return interface

    raise Exception("\tVM %s has no port on lb management network.", vmid)


def disable_port(net_driver, port):
    try:
        LOG.debug("\tDisable port %s.", port.port_id)

        if not CONF.dryrun:
            net_driver.neutron_client.update_port(
                port.port_id,
                {'port': {'admin_state_up': False}}
            )
    except (neutron_client_exceptions.NotFound,
            neutron_client_exceptions.PortNotFoundClient):
        raise Exception("Management port %s is not found in Neutron.",
                        port.port_id)


def upgrade_amps(session, net_driver, role=constants.ROLE_BACKUP):
    lb_amp_dict = {}
    amps = get_amps(session, role=role)

    for amp in amps:
        LOG.debug("[%s] Processing %s amphorae: %s, vm: %s",
                  amp.load_balancer_id, role, amp.id, amp.compute_id)

        lb_amp_dict[amp.load_balancer_id] = amp.id
        mgmt_port = get_vm_mgmt_port(net_driver, amp.compute_id,
                                     amp.lb_network_ip)
        disable_port(net_driver, mgmt_port)

    return lb_amp_dict


if __name__ == '__main__':
    raw_input('First, please stop octavia house_keeping process, then press '
              'any key to continue...')

    service.prepare_service(sys.argv)
    session = db_api.get_session()
    amp_repo = repo.AmphoraRepository()
    amphealth_repo = repo.AmphoraHealthRepository()
    nova_manager = nova_driver.VirtualMachineManager()
    net_driver = allowed_address_pairs.AllowedAddressPairsDriver()

    # Delete all the amp vms in spare pool and corresponding db records.
    amps = get_spare_amphoras(session)
    LOG.debug("Step 1: Clean up %d amphorae vms in spare pool.", len(amps))

    for amp in amps:
        delete_amp(nova_manager, session, amp_repo, amphealth_repo, amp)

    raw_input('Now, please start octavia house_keeping process, then press '
              'any key to continue...')

    # Wait for filling up the spare pool.
    LOG.debug("Step 2: Waiting for spare pool to fill up again...")
    check_spare_pool(amp_repo, session)

    # Find all slave amp vms of all loadbalancers, mark down their management
    # port. The fail over process could be triggered automatically.
    LOG.debug("Step 3: Begin to upgrade backup amphorae vms.")
    lb_amp_mapping = upgrade_amps(session, net_driver, constants.ROLE_BACKUP)
    wait_amps_failover(session, lb_amp_mapping, constants.ROLE_BACKUP)

    # TODO: Down the VIP port to trigger VRRP failover, so we can reduce the
    # interrupted time of VIP connection.
    LOG.debug("Sleep 60s before handling master amphorae vms...")
    time.sleep(60)

    # Find all master amp vms of all loadbalancers, mark down their management
    # port. The fail over process could be triggered automatically.
    LOG.debug("Step 4: Begin to upgrade master amphorae vms.")
    lb_amp_mapping = upgrade_amps(session, net_driver, constants.ROLE_MASTER)
    wait_amps_failover(session, lb_amp_mapping, constants.ROLE_MASTER)

    LOG.debug("Complete upgrading amphorae vms!")
