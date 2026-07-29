# HiveServer2 无法监听 10000：排障总结

## 最终结论

这次故障的直接根因不是内存不足、HDFS 权限、端口配置或 transport mode，而是 HiveServer2 初始化通知事件轮询时调用 Metastore 失败：

```text
NotificationEventPoll.initialize
getCurrentNotificationEventId
TApplicationException: Internal error processing get_current_notificationEventId
HiveServer2.init
```

因此 HiveServer2 不断重试并打印新的 `Hive Session ID`，但始终没有进入 Thrift 服务阶段，10000 端口也就不会监听。

最终有效修改是：

```xml
<property>
  <name>hive.metastore.event.db.notification.api.auth</name>
  <value>false</value>
</property>
```

这个配置由 Hive Metastore 服务读取。修改后，如果只重启 HiveServer2，旧 Metastore 进程仍使用旧配置，因此不会生效。停止旧 HiveServer2、重启 Metastore、确认 9083 监听，再只启动一个 HiveServer2 后，10000 端口出现，Beeline 连接及查询全部成功。

## 为什么看起来像“重启 Metastore 突然修好了”

真正完整的因果关系是：

1. 先通过 DEBUG 日志确定通知 API 调用失败。
2. 再把 `hive.metastore.event.db.notification.api.auth` 改为 `false`。
3. 旧 Metastore 尚未加载新配置。
4. 重启 Metastore 后新配置生效。
5. 新 HiveServer2 完成初始化并监听 10000。

所以，重启是让正确配置生效的必要步骤，但“单纯重启”不是根因修复。之前即使重启过 Metastore，如果当时配置尚未修改，或者仍有重复 HiveServer2 进程干扰，当然不会恢复。

## 关键证据

- HDFS 的 NameNode、DataNode、SecondaryNameNode 均正常。
- Metastore 的 9083 端口正常监听。
- `hive -e "show databases;"` 成功返回 `default`。
- `NOTIFICATION_LOG` 和 `NOTIFICATION_SEQUENCE` 均存在。
- HiveServer2 能创建 HDFS scratch 目录和 query-results cache。
- `jstack` 没有死锁、OOM；主线程在 `startHiveServer2` 的重试等待中。
- HiveServer2 失败时没有 Thrift 服务线程，也没有 10000 listener。
- 修复后：9083、10000 均监听；Beeline 连接 Hive 3.1.3；`show databases`、`show tables` 和 `select * from test_spark` 均成功。

## 没有解决根因的排查

- 把 HiveServer2 堆从 1024 MB 降到 512 MB：失败特征不变，也没有 OOM 证据。
- 降低 async/worker 线程数：只能减轻资源压力，不能修复 Metastore RPC 错误。
- 修改 HDFS `/tmp` 为 1777：属于合理规范化，但日志已证明目录可创建，并非阻塞点。
- 强制 `transport.mode=binary`：服务根本未进入 Thrift 初始化阶段。
- 反复检查 warehouse：warehouse 已存在，Hive CLI 已正常。
- 怀疑 notification 表缺失：两个表都存在，实际是 RPC 内部错误。
- 反复启动 HiveServer2：产生多个重试进程，混淆 PID、端口和日志证据。

## 下次最短排查流程

1. 用完整命令行确认 Metastore 和 HiveServer2 PID，避免把所有 `RunJar` 当成同一种服务。
2. 确保只保留一个 HiveServer2。
3. 检查 9083、10000 监听状态。
4. 用 `hive -e 'show databases;'` 分离 Metastore 基础健康和 HiveServer2 健康。
5. 若 10000 不监听，用 DEBUG 前台启动一次，优先搜索：
   - `NotificationEventPoll`
   - `get_current_notificationEventId`
   - `TApplicationException`
   - `Caused by`
6. 只有命中这条异常链时，才检查通知 API 鉴权配置。
7. 修改 Metastore 侧配置后，必须重启 Metastore；再启动一个干净的 HiveServer2。
8. 以“端口监听 + Beeline 查询成功”为完成标准，不能只看 JVM 存在或 Session ID。

## 资源情况的正确定位

4 GB 虚拟机、较高 Swap 使用量仍是后续运行 PySpark 时的重要风险，但它不是本次 10000 不监听的直接根因。只有出现 `OutOfMemoryError`、内核 OOM kill、分配失败或明显 GC 灾难时，才应把内存定为直接原因。
