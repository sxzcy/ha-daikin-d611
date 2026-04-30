# 大金 DTA117D611 Home Assistant 集成

[English](README.md) | [简体中文](README.zh-CN.md)

这是一个面向大金 New Life Multi DTA117D611 网关的 Home Assistant 自定义集成。
集成通过大金云端完成账号登录和网关发现，随后优先使用 DTA117D611 的本地
Socket 通道轮询和控制设备。

适用场景：大金 App 里已经可以看到本地 DTA117D611 网关，且该网关下已经接入
室内空调、VAM / Mini VAM 新风设备或空气传感器。

## 功能

- 通过 Home Assistant UI 配置流添加集成。
- 使用大金云端登录发现网关和本地 Socket 参数。
- 配置完成后通过本地 Socket 轮询设备状态。
- 室内空调设备作为 `climate` 实体。
- VAM / Mini VAM 新风设备作为 `fan` 实体。
- 温度、CO2、PM2.5、湿度、原始状态、刷新时间和控制结果等传感器。
- 在线、电源、异常和可选原始快照二进制传感器。
- 设备支持时提供运行模式和风量 `select` 实体。
- 优先使用网关 / 云端 payload 中的设备名称。
- 支持轮询间隔、超时、状态优先级、云端快照、稳定 ID 和诊断实体等选项。
- 支持 Home Assistant 诊断下载，并会脱敏账号、token、MAC、序列号和原始帧字段。

## 要求

- 推荐 Home Assistant 2026.3 或更新版本。
- 可登录大金 New Life Multi App 的大金账号。
- Home Assistant 所在网络可访问 DTA117D611 网关。
- 设备已经在大金 App 中接入网关。

## HACS 安装

1. 打开 HACS。
2. 添加本仓库为自定义仓库。
3. 仓库类型选择 `Integration`。
4. 安装 `Daikin DTA117D611`。
5. 重启 Home Assistant。
6. 进入 **设置 -> 设备与服务 -> 添加集成**。
7. 搜索 `Daikin DTA117D611` 并添加。

自定义仓库地址：

```text
https://github.com/sxzcy/ha-daikin-d611
```

## 手动安装

复制：

```text
custom_components/daikin_d611
```

到：

```text
<home-assistant-config>/custom_components/daikin_d611
```

然后重启 Home Assistant，并在 UI 中添加集成。

## 配置建议

首次配置建议：

- Gateway：可以填 `DTA117D611`，也可以填实际网关 key / MAC，例如
  `60180310B941`。
- Host/Port：先留空。集成会优先使用大金云端网关 payload 里的
  `socketIp/socketPort`。
- Scan interval：`60` 秒。
- Timeout：`10` 秒。

如果账号下只有一个网关，即使输入的 Gateway 字段没有精确匹配云端网关名称，
集成也会自动使用唯一网关。

如果云端发现网关成功，但本地 Socket 连接失败，可以手动填写路由器里看到的网关
地址和端口，或根据抓包结果填写 Host/Port。

## 说明和限制

- 添加集成时仍然需要大金云端登录，用于发现网关和获取用户上下文。
- 运行时默认本地状态优先。云端快照可以在选项中开启，作为补充状态或调试来源。
- 本地控制能力取决于 DTA117D611 网关固件和已接入设备支持的命令集。
- 部分大金 payload 字段未公开文档说明。集成会尽量把未知字段保留在诊断属性中。
- 新安装默认使用稳定物理 ID。已有安装可以在选项中切换，用于从旧的房间号 ID
  迁移。
- 本项目独立于 `ha-dsair`。`ha-dsair` 主要面向 DTA117B611/DTA117C611 旧型号，
  不覆盖本项目观察到的 DTA117D611 Mini VAM 设备类型。

## 公开发布注意事项

请不要把 APK、反编译源码、本地抓包、账号密码、token、网关私有信息或个人家庭
数据提交到公开仓库。

