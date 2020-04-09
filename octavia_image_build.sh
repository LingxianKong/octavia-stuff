#!/usr/bin/env bash
#
# Copyright 2019 Catalyst IT Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# expected to run the script inside a vm with sudo permission.

set -e

ARGS=`getopt -o h --long workdir:,size:,release:,skip-setup,os:,os-release:,password:,clean-before:,output:,upstream -- "$@"`
if [ $? != 0 ]; then
    echo "Terminating..."
    exit 1
fi

eval set -- "${ARGS}"
while true
do
    case "$1" in
        --workdir)
            WORKDIR=$2;
            shift 2
            ;;
        --size)
            IMAGE_SIZE=$2;
            shift 2
            ;;
        --skip-setup)
            SKIP_HOST_SETUP="true"
            shift
            ;;
        --clean-before)
            CLEAN=$2
            shift 2
            ;;
        --release)
            OCTAVIA_RELEASE=$2
            shift 2
            ;;
        --os)
            IMAGE_OS=$2
            shift 2
            ;;
        --os-release)
            IMAGE_OS_RELEASE=$2
            shift 2
            ;;
        --password)
            IMAGE_PASSWORD=$2
            shift 2
            ;;
        --output)
            OUTPUT=$2;
            shift 2
            ;;
        --upstream)
            UPSTREAM="true";
            shift 1
            ;;
        --)
            break
            ;;
        *)
            echo "Unrecognized param."
            exit 1
            ;;
    esac
done

WORKDIR=${WORKDIR:-"/opt/amphora_image"}
IMAGE_SIZE=${IMAGE_SIZE:-2}
SKIP_HOST_SETUP=${SKIP_HOST_SETUP:-"false"}
CLEAN=${CLEAN:-"true"}
IMAGE_OS=${IMAGE_OS:-"ubuntu"}
IMAGE_OS_RELEASE=${IMAGE_OS_RELEASE:-"bionic"}
IMAGE_PASSWORD=${IMAGE_PASSWORD:-""}
today=$(date +%Y%m%d)
OUTPUT=${OUTPUT:-"$(pwd)/octavia-${OCTAVIA_RELEASE}-${IMAGE_OS}-${IMAGE_OS_RELEASE}-${today}.raw"}
UPSTREAM=${UPSTREAM:-'false'}

function package_setup {
  apt-get update
  apt-get install -y --no-install-recommends -qq \
    git qemu kpartx debootstrap \
    build-essential python-dev python-setuptools libffi-dev libxslt1-dev libxml2-dev libyaml-dev libssl-dev
  curl https://bootstrap.pypa.io/get-pip.py | python -
  pip install -U \
    diskimage-builder \
    python-openstackclient \
    python-octaviaclient
}

function create_image {
  export GIT_SSL_NO_VERIFY=1
  rm -rf ~/.cache/image-create

  # Re-create the workdir folder
  if [[ "$CLEAN" == "true" ]]; then
    rm -rf ${WORKDIR} && mkdir -p ${WORKDIR}
    pushd ${WORKDIR}

    if [[ "$UPSTREAM" == "true" ]]; then
      git clone https://opendev.org/openstack/octavia octavia --branch stable/${OCTAVIA_RELEASE}
    else
      git clone https://gitlab.int.catalystcloud.nz/catalystcloud/octavia.git octavia --branch catalyst/stable/${OCTAVIA_RELEASE}
    fi
  else
    pushd ${WORKDIR}
  fi

  echo '====================================> Starting to create amphora image'
  pushd octavia/diskimage-create

  params="-o ${OUTPUT} -w ${WORKDIR}/octavia -i ${IMAGE_OS} -s ${IMAGE_SIZE} -d ${IMAGE_OS_RELEASE} -t raw"
  if [[ ${IMAGE_PASSWORD} != "" ]]; then
    params="${params} -r ${IMAGE_PASSWORD}"
  fi

  if [[ "${IMAGE_OS}" = "fedora" ]]; then
    export DIB_RELEASE=${IMAGE_OS_RELEASE}
    # For fedora 29
    export DIB_DISTRIBUTION_MIRROR="http://fedora-alt.mirror.liquidtelecom.com/fedora/linux/"
    # For fedora 28
    # export DIB_DISTRIBUTION_MIRROR="https://archives.fedoraproject.org/pub/archive/fedora/linux"
    export DIB_LOCAL_IMAGE=/home/lingxiankong/workdir/test/octavia/images/Fedora-Cloud-Base-29-1.2.x86_64.qcow2
  fi

  ./diskimage-create.sh ${params}
  ret=$?
  popd
  popd

  if [ $ret -ne 0 ]; then
    echo 'Failed to create amphora image.'
    exit 1
  fi

  rm -rf ~/.cache/image-create
  echo '====================================> Image created successfully!'
}

if [[ "${SKIP_HOST_SETUP}" == "false" ]]; then
  package_setup
fi

create_image