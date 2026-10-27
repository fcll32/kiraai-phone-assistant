# Android 控制服务源码

1.0.0 的手机界面在 `uni-app/`。安装和操作请看 [手机说明](../uni-app/README.md)，服务器配置请看 [新手使用说明](../新手使用说明.md)。

此目录保留无障碍服务、连接服务、指令有效期检查、地址转换和旧版 MainActivity。新版通过 PhoneRuntime 与 UTS 桥接调用服务，不使用旧版 Activity。

修改服务后运行 `python scripts/sync_uni_native.py --write`，再重新编译资源和 APK。不要把本目录单独构建的旧界面 APK 当作新版 uni-app APK 发布。
