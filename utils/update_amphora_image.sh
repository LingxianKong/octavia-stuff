#!/bin/bash
set -e

usage() {
    echo
    echo "Usage: $(basename $0)"
    echo "            [-d **/opt/stack/octavia** | <octavia directory path> ]"
    echo "            [-n **amphora-x64-haproxy** | <image name in glance> ]"
    echo "            [-b **master** | <code branch for amphora agent> ]"
    echo "            [-h]"
    echo
    exit 1
}

while getopts "hd:n:b:" opt; do
    case $opt in
        h)
            usage
        ;;
        d)
            OCTAVIA_DIR=$OPTARG
        ;;
        n)
            GLANCE_IMAGE_NAME=$OPTARG
        ;;
        b)
            AMPHORA_AGENT_BRANCH=$OPTARG
        ;;
        *)
            usage
        ;;
    esac
done

OCTAVIA_DIR=${OCTAVIA_DIR:-"/opt/stack/octavia"}
GLANCE_IMAGE_NAME=${GLANCE_IMAGE_NAME:-"amphora-x64-haproxy"}
AMPHORA_AGENT_BRANCH=${AMPHORA_AGENT_BRANCH:-"master"}

if [ "$AMPHORA_AGENT_BRANCH" != 'master' ]; then
    sed -i "s:octavia.*:octavia stable/$AMPHORA_AGENT_BRANCH:" $OCTAVIA_DIR/elements/amphora-agent-ubuntu/source-repository-amphora-agent
fi

echo "Creating image using octavia diskimage-create tool..."
$OCTAVIA_DIR/diskimage-create/diskimage-create.sh -s 2
echo "Amphora image created successfully!"

IMAGE_ID=$(glance image-list --tag amphora | awk '/'"$GLANCE_IMAGE_NAME"'/ {print $2}')

if [ $IMAGE_ID ]; then
    echo "Find amphora image id: $IMAGE_ID"
    echo "Delete the old image $IMAGE_ID"
    #glance image-delete $IMAGE_ID
fi

echo "Creating new amphora image in Glance."
NEW_IMAGE_ID=$(glance image-create --name $GLANCE_IMAGE_NAME --visibility public --container-format bare --disk-format qcow2 --file $OCTAVIA_DIR/diskimage-create/amphora-x64-haproxy.qcow2 | awk '/ id / {print $4}')
echo "A new image $NEW_IMAGE_ID created in Glance."

echo "Updating image's tag."
glance image-tag-update $NEW_IMAGE_ID amphora

echo "Amphora image created/updated in Glance successfully!"
