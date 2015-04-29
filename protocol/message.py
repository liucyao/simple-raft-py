#!/usr/bin/python
# -*- coding:utf-8 -*-


class Message(object):
    """
    消息类
    TODO 这里解析做的太乱了。。
    """
    @staticmethod
    def parse(data, client):
        """
        解析原始字符串信息
        """
        if data is None:
            return None
        elif data.startswith('get') and ';' not in data:
            # 客户端发来的get操作
            tokens = data.split()
            if len(tokens) == 2:
                return ClientMessage('get', tokens[1])
            else:
                return InvalidMessage('Invalid GET operation format:%s' % data)
        elif data.startswith('del'):
            auto_commit = False
            if data.endswith(';commit'):
                auto_commit = True
                data = data.split(';')[0]
            tokens = data.split()
            if len(tokens) == 2:
                return ClientMessage('delete', tokens[1], None, auto_commit)
            else:
                return InvalidMessage('Invalid DEL operation format:%s' % data)
        elif data.startswith('set'):
            # 客户端发来的set操作
            auto_comit = False
            if data.endswith(';commit'):
                auto_comit = True
                data = data.split(';')[0]
            tokens = data.split()
            if len(tokens) == 3:
                return ClientMessage('set', tokens[1], tokens[2], auto_comit)
            else:
                return InvalidMessage('Invalid SET operation format:%s' % data)
        elif data == 'commit':
            # 客户端发来的提交
            return ClientMessage('commit')
        elif data == 'rollback':
            return ClientMessage('rollback')
        elif data.startswith('#'):
            # 来自其他节点的请求消息
            # node message格式
            # #ip:port#msgbody
            # node message需要提供消息来源
            # client.getpeername()也能获取消息来源，但是端口号并不是node监听的端口
            # 如果只是用ip作为node的标示，那么都在本地127.0.0.1上的node就会冲突
            # 所以node作为client连接过来的时候，需要加上来源 ip:port
            data = data[1:]  # 去掉最开始的#
            token = data.split('#')
            if not token or len(token) < 2:
                return InvalidMessage('Invalid Node Message Format')
            source = token[0]
            ip_port = source.split(':')
            if not ip_port or len(ip_port) != 2:
                return InvalidMessage('invalid source ip:port format:%s' % ip_port)
            ip = ip_port[0]
            if ip != client.getpeername()[0]:
                return InvalidMessage('IP %s in message source not eq IP  %s in socket' % (ip, client.getpeername()[0]))
            try:
                port = int(ip_port[1])
            except ValueError, e:
                return InvalidMessage('Invalid port:%s , error: %s' % (ip_port[1], e))
            node_key = (ip, port)
            data = token[1].strip()
            if data == 'elect':
                return ElectRequestMessage(node_key)
            elif data.startswith('heartbeat'):
                heartbeat_msg_body = data.split()
                alives_info = heartbeat_msg_body[1].split(',')
                if not alives_info and len(alives_info) % 2 != 0:
                    return InvalidMessage('Invalid alive nodes info')
                alives = []
                for i in xrange(0, len(alives_info), 2):
                    alives.append((alives_info[i], int(alives_info[i+1]), ))
                heartbeat_extra_msg_body = ' '.join(heartbeat_msg_body[2:])
                extra_msg = Message.parse(heartbeat_extra_msg_body, client)
                if not isinstance(extra_msg, ClientMessage):
                    extra_msg = None
                return HeartbeatRequestMessage(node_key, alives, extra_msg)
            else:
                return InvalidMessage('Invalid Node Request Message:%s' % data)
        elif data.startswith('@'):
            # 来自其他节点的应答消息
            # message format
            # @ip:port@msgbody value
            data = data[1:].strip()
            token = data.split('@')
            if not token or len(token) < 2:
                return InvalidMessage('Invalid Node Response Message Format')
            source = token[0]
            ip_port = source.split(':')
            if not ip_port or len(ip_port) != 2:
                return InvalidMessage('Invalid source ip:port format:%s' % ip_port)
            ip = ip_port[0]
            try:
                port = int(ip_port[1])
            except ValueError, e:
                return InvalidMessage('Invalid port:%s , error: %s' % (ip_port[1], e))
            node_key = (ip, port)
            data = token[1].strip()
            if data.startswith('elect'):
                token = data.split()
                if not token or len(token) != 2:
                    return InvalidMessage('Invalid Node Elect Response Message:%s' % data)
                try:
                    value = int(token[1])
                    return ElectResponseMessage(node_key, value)
                except ValueError, e:
                    return InvalidMessage(e)
            elif data.startswith('heartbeat'):
                # 心跳响应
                token = data.split()
                if not token or len(token) != 2:
                    return InvalidMessage('Invalid Node Heartbeat Response Message:%s' % data)
                try:
                    value = int(token[1])
                    return HeartbeatResponseMessage(node_key, value)
                except ValueError, e:
                    return InvalidMessage(e)
            else:
                return InvalidMessage('Invalid Response Message:%s' % data)
        else:
            # 暂时忽略其他节点发来的信息
            return InvalidMessage('Invalild Message:%s' % data)


class ClientMessage(Message):
    """
    客户端发来的消息
    """

    def __init__(self, op, key=None, value=None, auto_commit=False):
        self.op = op
        self.key = key
        self.value = value
        self.auto_commit = auto_commit

    def __str__(self):
        return '[%s]%s:%s' % (self.op, self.key, self.value)


class NodeMessage(Message):
    """
    cluster中其他node发来的消息
    """
    pass


class ElectRequestMessage(NodeMessage):
    """
    发起选举请求的消息
    消息格式：
        #candidate_host:candidate_port#elect
    """

    def __init__(self, candidate):
        """
        :param candidate 选举发起节点node key
        """
        self.candidate = candidate


class ElectResponseMessage(NodeMessage):
    """
    响应选取结果的消息
    消息格式：
        @follower_host:follower_port@elect 1/0
    """

    def __init__(self, follower, value):
        """
        :param follower 参与选举的follower的node key
        :param value    选举结果0已经选举其他node 1选取
        """
        self.follower = follower
        self.value = value


class HeartbeatRequestMessage(NodeMessage):
    """
    leader发起的心跳
    消息格式：
        #leader_host:leader_port#heartbeat alivenode1_host,alivenode1_port,alivenode2_host,alivenode2_port... extra_msg
    """

    def __init__(self, leader, alives, message=None):
        """
        构造方法
        :param leader:  发出心跳的leader的node_key
        :param alives:  活跃节点列表，同步给其他follower
        :param message: 用于leader与follower同步数据，client message类型
        :return:
        """
        self.leader = leader
        self.alives = alives
        self.message = message


class HeartbeatResponseMessage(NodeMessage):
    """
    Follower响应leader心跳请求
    消息格式:
        @folloer_host:follower_port@heartbeat 1/0
    """
    def __init__(self, follower, value):
        """
        构造方法
        :param follower:  follower节点node key
        :param value:     响应的结果
        :return:
        """
        self.follower = follower
        self.value = value


class InvalidMessage(Message):
    """
    非法格式消息
    """
    def __init__(self, msg='invalid message'):
        """
        构造方法
        :param msg:
        :return:
        """
        self.message = msg

    def __str__(self):
        return self.message