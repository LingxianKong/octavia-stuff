# Multi-node Octavia Deployment

时间：2017.04.12
版本：Pike dev cycle

社区的octavia repo里面提供的multi-node部署脚本，是api、network、compute所有服务all-in-one一个node，还有一个compute+octavia一个node，两个octavia-api跑在一个haproxy后面。

而生产环境中，api服务一般不会跑在network node上，所以我的多节点devstack环境中，network node是独立部署，octavia-api在api node，octavia的worker、health-manager、house-keeper跑在network node上，因为它们需要同时与虚拟机和OpenStack各个服务通信。

所以，我对octavia社区提供的devstack安装脚本做了一些小的改动。

同时，我提供了两套Vagrantfile，支持openstack和virtualbox作为provider。你需要根据你的环境修改一些配置(主要是IP地址)。这里我以virtualbox为例简单列一下过程：

    vagrant up

    #先配置api node
    vagrant ssh main
    sudo -s
    cd devstack
    export HOST_IP=192.168.33.17
    chmod +x tools/create-stack-user.sh
    ./tools/create-stack-user.sh
    chown -R stack:stack /home/ubuntu/devstack
    su - stack
    vi /home/ubuntu/devstack/local.conf
    # 拷贝local.conf.octavia.main.txt文件内容
    cd /opt/stack
    git clone https://git.openstack.org/openstack/octavia
    > octavia/devstack/plugin.sh
    vi octavia/devstack/plugin.sh
    # 拷贝devstack-plugin-main.sh文件内容

    cd /home/ubuntu/devstack
    ./stack.sh

    #再配置network node
    vagrant ssh second
    sudo -s
    cd devstack
    export HOST_IP=192.168.33.18
    chmod +x tools/create-stack-user.sh
    ./tools/create-stack-user.sh
    chown -R stack:stack /home/ubuntu/devstack
    su - stack
    vi /home/ubuntu/devstack/local.conf
    # 拷贝local.conf.octavia.second.txt文件内容
    cd /opt/stack
    git clone https://git.openstack.org/openstack/octavia
    > octavia/devstack/plugin.sh
    vi octavia/devstack/plugin.sh
    # 拷贝devstack-plugin-second.sh文件内容

    cd /home/ubuntu/devstack
    ./stack.sh

因为是在虚拟机中部署octavia，amphorae是运行在嵌套的虚拟环境下，性能比较差，所以需要修改一些配置（主要是一些timeout和retry）来保证功能正常：

    [health_manager]
    health_check_interval = 10
    [haproxy_amphora]
    rest_request_conn_timeout = 600
    rest_request_read_timeout = 600
    [controller_worker]
    amp_active_retries = 100
    amp_active_wait_sec = 5